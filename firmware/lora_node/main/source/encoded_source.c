#include "source/encoded_source.h"
#include <stdatomic.h>
#include <string.h>

#define SLOTS 4U
#define NO_SLOT UINT32_MAX
#define FRAMES_PER_MESSAGE 150U

enum
{
    SLOT_FREE,
    SLOT_FILLING,
    SLOT_READY,
    SLOT_ACTIVE
};
struct encoded_queue
{
    encoded_source_memory memory;
    const uint8_t *reference;
    uint8_t *data;
    uint32_t *actual_times;
    encoded_source_sample *samples;
    atomic_uint sample_count;
    uint32_t next_sample;
    int64_t started_us, production_end_us, drain_deadline_us;
    uint32_t drain_us, next_frame, fill_slot, active_slot;
    bool dropping;
    atomic_uint producer_version, consumer_version;
    atomic_bool cutoff, cancel;
    struct
    {
        atomic_uint state, bytes, message;
    } slots[SLOTS];
#define FIELD(name) atomic_uint name;
    SOURCE_COUNTERS(FIELD)
#undef FIELD
};

static void wipe(void *pointer, size_t bytes)
{
    volatile uint8_t *out = pointer;
    while (bytes--)
        *out++ = 0;
}
static void maximum(atomic_uint *value, uint32_t candidate)
{
    unsigned previous = atomic_load(value);
    while (previous < candidate && !atomic_compare_exchange_weak(value, &previous, candidate))
    {
    }
}
encoded_queue *encoded_queue_create(encoded_source_memory memory, const void *reference,
                                    size_t bytes, uint32_t drain_us)
{
    if (!reference || bytes != SOURCE_MESSAGE_BYTES || drain_us > SOURCE_MAX_DRAIN_US ||
        !memory.allocate || !memory.release)
        return NULL;
    encoded_queue *q = memory.allocate(memory.context, sizeof(*q));
    if (!q)
        return NULL;
    memset(q, 0, sizeof(*q));
    q->memory = memory;
    q->reference = reference;
    q->drain_us = drain_us;
    q->fill_slot = q->active_slot = NO_SLOT;
#define FIELD(name) atomic_init(&q->name, 0);
    SOURCE_COUNTERS(FIELD)
#undef FIELD
    atomic_init(&q->producer_version, 0);
    atomic_init(&q->consumer_version, 0);
    atomic_init(&q->sample_count, 0);
    atomic_init(&q->cutoff, false);
    atomic_init(&q->cancel, false);
    for (unsigned i = 0; i < SLOTS; i++)
    {
        atomic_init(&q->slots[i].state, SLOT_FREE);
        atomic_init(&q->slots[i].bytes, 0);
        atomic_init(&q->slots[i].message, 0);
    }
    q->data = memory.allocate(memory.context, SOURCE_QUEUE_BYTES);
    q->actual_times = memory.allocate(memory.context, SOURCE_FRAMES * sizeof(uint32_t));
    q->samples = memory.allocate(memory.context, SOURCE_AUDIT_ROWS * sizeof(*q->samples));
    if (!q->data || !q->actual_times || !q->samples)
    {
        encoded_queue_destroy(q);
        return NULL;
    }
    memset(q->data, 0, SOURCE_QUEUE_BYTES);
    memset(q->actual_times, 0xff, SOURCE_FRAMES * sizeof(uint32_t));
    return q;
}
bool encoded_queue_start(encoded_queue *q, int64_t start)
{
    if (!q || start < 0 || start > INT64_MAX - SOURCE_DURATION_US - SOURCE_MAX_DRAIN_US ||
        atomic_load(&q->phase) != SOURCE_PREPARED || q->started_us)
        return false;
    q->started_us = start;
    q->production_end_us = start + SOURCE_DURATION_US;
    q->drain_deadline_us = q->production_end_us + q->drain_us;
    atomic_store_explicit(&q->phase, SOURCE_PRODUCING, memory_order_release);
    return true;
}
static void discard_pending(encoded_queue *q, bool partial_only)
{
    for (unsigned i = 0; i < SLOTS; i++)
    {
        unsigned previous = atomic_load(&q->slots[i].state);
        if (previous != SLOT_FILLING && (partial_only || previous != SLOT_READY))
            continue;
        if (!atomic_compare_exchange_strong(&q->slots[i].state, &previous, SLOT_FREE))
            continue;
        uint32_t bytes = atomic_exchange(&q->slots[i].bytes, 0);
        atomic_fetch_or(&q->discarded_message_mask, 1U << (atomic_load(&q->slots[i].message) - 1));
        if (previous == SLOT_READY)
        {
            atomic_fetch_add(&q->queue_discarded_messages, 1);
            atomic_fetch_add(&q->queue_discarded_bytes, bytes);
        }
        else
            atomic_fetch_add(&q->partial_discarded_bytes, bytes);
        atomic_fetch_sub(&q->occupancy_bytes, bytes);
        wipe(q->data + i * SOURCE_MESSAGE_BYTES, SOURCE_MESSAGE_BYTES);
    }
    q->fill_slot = NO_SLOT;
}
static void produce(encoded_queue *q, int64_t now)
{
    unsigned frame = q->next_frame;
    unsigned offset = frame % FRAMES_PER_MESSAGE;
    if (!offset)
    {
        q->fill_slot = NO_SLOT;
        for (unsigned i = 0; i < SLOTS; i++)
        {
            unsigned expected = SLOT_FREE;
            if (!atomic_compare_exchange_strong(&q->slots[i].state, &expected, SLOT_FILLING))
                continue;
            q->fill_slot = i;
            atomic_store(&q->slots[i].bytes, 0);
            atomic_store(&q->slots[i].message, frame / FRAMES_PER_MESSAGE + 1);
            break;
        }
        q->dropping = q->fill_slot == NO_SLOT;
        if (q->dropping)
            atomic_fetch_or(&q->overflow_message_mask, 1U << (frame / FRAMES_PER_MESSAGE));
    }
    uint32_t elapsed = (uint32_t)(now - q->started_us);
    uint32_t lateness = elapsed - frame * SOURCE_FRAME_US;
    q->actual_times[frame] = elapsed;
    if (lateness >= SOURCE_FRAME_US)
        atomic_fetch_add(&q->late_frames, 1);
    maximum(&q->max_lateness_us, lateness);
    atomic_fetch_add(&q->frames_produced, 1);
    atomic_fetch_add(&q->produced_bytes, SOURCE_FRAME_BYTES);
    if (q->dropping)
        atomic_fetch_add(&q->overflow_dropped_bytes, SOURCE_FRAME_BYTES);
    else
    {
        memcpy(q->data + q->fill_slot * SOURCE_MESSAGE_BYTES + offset * SOURCE_FRAME_BYTES,
               q->reference + offset * SOURCE_FRAME_BYTES, SOURCE_FRAME_BYTES);
        atomic_store(&q->slots[q->fill_slot].bytes, (offset + 1) * SOURCE_FRAME_BYTES);
        atomic_fetch_add(&q->admitted_bytes, SOURCE_FRAME_BYTES);
        unsigned used =
            atomic_fetch_add(&q->occupancy_bytes, SOURCE_FRAME_BYTES) + SOURCE_FRAME_BYTES;
        maximum(&q->peak_occupancy_bytes, used);
    }
    if (offset + 1 == FRAMES_PER_MESSAGE)
    {
        if (q->dropping)
            atomic_fetch_add(&q->dropped_messages, 1);
        else
        {
            atomic_fetch_add(&q->admitted_messages, 1);
            atomic_fetch_or(&q->admitted_message_mask, 1U << (frame / FRAMES_PER_MESSAGE));
            atomic_store_explicit(&q->slots[q->fill_slot].state, SLOT_READY, memory_order_release);
        }
        q->fill_slot = NO_SLOT;
    }
    q->next_frame++;
    atomic_store_explicit(&q->trace_frames, q->next_frame, memory_order_release);
}
static void sample(encoded_queue *q, int64_t now)
{
    uint64_t elapsed = (uint64_t)(now - q->started_us);
    if (elapsed < q->next_sample || q->next_sample > SOURCE_DURATION_US + q->drain_us)
        return;
    unsigned index = atomic_load(&q->sample_count);
    if (index >= SOURCE_AUDIT_ROWS)
        return;
    uint32_t planned = q->next_sample;
    uint32_t skipped = (elapsed - planned) / SOURCE_AUDIT_US;
    q->samples[index] = (encoded_source_sample){
        index, planned, elapsed > UINT32_MAX ? UINT32_MAX : elapsed, skipped, {0}};
    encoded_queue_snapshot(q, &q->samples[index].status);
    q->next_sample = planned + (skipped + 1) * SOURCE_AUDIT_US;
    atomic_store_explicit(&q->sample_count, index + 1, memory_order_release);
}
void encoded_queue_step(encoded_queue *q, int64_t now)
{
    if (!q)
        return;
    unsigned phase = atomic_load_explicit(&q->phase, memory_order_acquire);
    if (phase == SOURCE_PREPARED || now < q->started_us)
        return;
    if (phase >= SOURCE_FINISHED)
    {
        sample(q, now);
        return;
    }
    atomic_fetch_add(&q->producer_version, 1);
    if (atomic_load(&q->cancel))
    {
        atomic_store(&q->frames_cancelled, SOURCE_FRAMES - q->next_frame);
        discard_pending(q, false);
        atomic_store(&q->phase,
                     atomic_load(&q->occupancy_bytes) ? SOURCE_DRAINING : SOURCE_CANCELLED);
    }
    else
    {
        if (phase == SOURCE_PRODUCING)
        {
            if (now < q->production_end_us)
                while (q->next_frame < SOURCE_FRAMES &&
                       !atomic_load_explicit(&q->cancel, memory_order_acquire) &&
                       q->started_us + (int64_t)q->next_frame * SOURCE_FRAME_US <= now)
                    produce(q, now);
            else
            {
                atomic_store(&q->frames_missed, SOURCE_FRAMES - q->next_frame);
                q->next_frame = SOURCE_FRAMES;
                atomic_store_explicit(&q->trace_frames, SOURCE_FRAMES, memory_order_release);
                discard_pending(q, true);
                atomic_store(&q->phase, SOURCE_DRAINING);
            }
        }
        if (atomic_load(&q->phase) == SOURCE_DRAINING)
        {
            if (now >= q->drain_deadline_us)
            {
                atomic_store(&q->cutoff, true);
                discard_pending(q, false);
            }
            if (!atomic_load(&q->occupancy_bytes))
                atomic_store(&q->phase, SOURCE_FINISHED);
        }
    }
    atomic_fetch_add(&q->producer_version, 1);
    sample(q, now);
}
bool encoded_queue_take(encoded_queue *q, encoded_source_message *out)
{
    if (!q || !out || q->active_slot != NO_SLOT || atomic_load(&q->cancel) ||
        atomic_load(&q->cutoff))
        return false;
    unsigned phase = atomic_load_explicit(&q->phase, memory_order_acquire);
    if (phase != SOURCE_PRODUCING && phase != SOURCE_DRAINING)
        return false;
    unsigned selected = NO_SLOT, message = UINT32_MAX;
    for (unsigned i = 0; i < SLOTS; i++)
    {
        if (atomic_load_explicit(&q->slots[i].state, memory_order_acquire) != SLOT_READY)
            continue;
        unsigned id = atomic_load(&q->slots[i].message);
        if (id < message)
        {
            selected = i;
            message = id;
        }
    }
    if (selected == NO_SLOT)
        return false;
    atomic_fetch_add(&q->consumer_version, 1);
    unsigned expected = SLOT_READY;
    bool acquired =
        atomic_compare_exchange_strong(&q->slots[selected].state, &expected, SLOT_ACTIVE);
    if (acquired && atomic_load(&q->slots[selected].message) != message)
    {
        atomic_store_explicit(&q->slots[selected].state, SLOT_READY, memory_order_release);
        acquired = false;
    }
    if (acquired)
    {
        q->active_slot = selected;
        *out = (encoded_source_message){message, q->data + selected * SOURCE_MESSAGE_BYTES,
                                        SOURCE_MESSAGE_BYTES};
        atomic_fetch_add(&q->taken_messages, 1);
    }
    atomic_fetch_add(&q->consumer_version, 1);
    return acquired;
}
bool encoded_queue_complete(encoded_queue *q, uint32_t message, encoded_source_outcome outcome)
{
    if (!q || q->active_slot == NO_SLOT || outcome > SOURCE_DISCARDED)
        return false;
    unsigned slot = q->active_slot;
    if (atomic_load(&q->slots[slot].message) != message)
        return false;
    atomic_fetch_add(&q->consumer_version, 1);
    if (outcome == SOURCE_SENT)
    {
        atomic_fetch_or(&q->sent_message_mask, 1U << (message - 1));
        atomic_fetch_add(&q->sent_messages, 1);
        atomic_fetch_add(&q->sent_bytes, SOURCE_MESSAGE_BYTES);
    }
    else if (outcome == SOURCE_FAILED)
    {
        atomic_fetch_or(&q->failed_message_mask, 1U << (message - 1));
        atomic_fetch_add(&q->failed_messages, 1);
        atomic_fetch_add(&q->failed_bytes, SOURCE_MESSAGE_BYTES);
    }
    else
    {
        atomic_fetch_or(&q->discarded_message_mask, 1U << (message - 1));
        atomic_fetch_add(&q->consumer_discarded_bytes, SOURCE_MESSAGE_BYTES);
    }
    wipe(q->data + slot * SOURCE_MESSAGE_BYTES, SOURCE_MESSAGE_BYTES);
    atomic_fetch_sub(&q->occupancy_bytes, SOURCE_MESSAGE_BYTES);
    atomic_store(&q->slots[slot].bytes, 0);
    atomic_store_explicit(&q->slots[slot].state, SLOT_FREE, memory_order_release);
    q->active_slot = NO_SLOT;
    if (atomic_load(&q->phase) == SOURCE_DRAINING && !atomic_load(&q->occupancy_bytes))
        atomic_store(&q->phase, atomic_load(&q->cancel) ? SOURCE_CANCELLED : SOURCE_FINISHED);
    atomic_fetch_add(&q->consumer_version, 1);
    return true;
}
void encoded_queue_snapshot(const encoded_queue *q, encoded_source_status *out)
{
    if (!q || !out)
        return;
    for (unsigned attempt = 0; attempt < 3; attempt++)
    {
        unsigned producer = atomic_load_explicit(&q->producer_version, memory_order_acquire);
        unsigned consumer = atomic_load_explicit(&q->consumer_version, memory_order_acquire);
        *out = (encoded_source_status){.started_us = q->started_us,
                                       .production_end_us = q->production_end_us,
                                       .drain_deadline_us = q->drain_deadline_us};
#define FIELD(name) out->name = atomic_load(&q->name);
        SOURCE_COUNTERS(FIELD)
#undef FIELD
        unsigned total = 0;
        for (unsigned i = 0; i < SLOTS; i++)
        {
            unsigned state = atomic_load_explicit(&q->slots[i].state, memory_order_acquire);
            unsigned bytes = atomic_load(&q->slots[i].bytes);
            if (state == SLOT_READY)
                out->ready_messages++;
            if (state == SLOT_ACTIVE)
                out->active_bytes += bytes;
            if (state == SLOT_FILLING)
                out->partial_bytes += bytes;
            if (state != SLOT_FREE)
                total += bytes;
        }
        out->drain_cutoff = atomic_load(&q->cutoff);
        out->cancel_requested = atomic_load(&q->cancel);
        out->consistent =
            !(producer & 1) && !(consumer & 1) && total == out->occupancy_bytes &&
            producer == atomic_load_explicit(&q->producer_version, memory_order_acquire) &&
            consumer == atomic_load_explicit(&q->consumer_version, memory_order_acquire);
        if (out->consistent)
            return;
    }
}
size_t encoded_queue_trace(const encoded_queue *q, uint32_t first, encoded_source_trace *out,
                           size_t count)
{
    if (!q || !out)
        return 0;
    unsigned available = atomic_load_explicit(&q->trace_frames, memory_order_acquire);
    if (first >= available)
        return 0;
    if (count > available - first)
        count = available - first;
    for (size_t i = 0; i < count; i++)
    {
        uint32_t index = first + i;
        out[i] = (encoded_source_trace){index, index * SOURCE_FRAME_US, q->actual_times[index],
                                        q->actual_times[index] != UINT32_MAX};
    }
    return count;
}
size_t encoded_queue_samples(const encoded_queue *q, uint32_t first, encoded_source_sample *out,
                             size_t count)
{
    if (!q || !out)
        return 0;
    unsigned available = atomic_load_explicit(&q->sample_count, memory_order_acquire);
    if (first >= available)
        return 0;
    if (count > available - first)
        count = available - first;
    memcpy(out, q->samples + first, count * sizeof(*out));
    return count;
}
void encoded_queue_request_stop(encoded_queue *q)
{
    if (!q)
        return;
    atomic_store_explicit(&q->cancel, true, memory_order_release);
    unsigned expected = SOURCE_PREPARED;
    if (atomic_compare_exchange_strong(&q->phase, &expected, SOURCE_CANCELLED))
        atomic_store(&q->frames_cancelled, SOURCE_FRAMES);
}
bool encoded_queue_retire_payload(encoded_queue *q)
{
    if (!q || atomic_load(&q->phase) < SOURCE_FINISHED || atomic_load(&q->occupancy_bytes))
        return false;
    if (q->data)
    {
        wipe(q->data, SOURCE_QUEUE_BYTES);
        q->memory.release(q->memory.context, q->data);
        q->data = NULL;
    }
    q->reference = NULL;
    return true;
}
void encoded_queue_destroy(encoded_queue *q)
{
    if (!q)
        return;
    encoded_source_memory memory = q->memory;
    if (q->data)
    {
        wipe(q->data, SOURCE_QUEUE_BYTES);
        memory.release(memory.context, q->data);
    }
    if (q->actual_times)
    {
        wipe(q->actual_times, SOURCE_FRAMES * sizeof(uint32_t));
        memory.release(memory.context, q->actual_times);
    }
    if (q->samples)
    {
        wipe(q->samples, SOURCE_AUDIT_ROWS * sizeof(*q->samples));
        memory.release(memory.context, q->samples);
    }
    wipe(q, sizeof(*q));
    memory.release(memory.context, q);
}
void encoded_queue_memory(const encoded_queue *q, node_memory_inventory *out)
{
    if (!q)
        return;
    node_memory_add(out, "source_owner", q, sizeof(*q));
    node_memory_add(out, "source_queue", q->data, SOURCE_QUEUE_BYTES);
    node_memory_add(out, "source_audit", q->samples, SOURCE_AUDIT_ROWS * sizeof(*q->samples));
    node_memory_add(out, "source_trace", q->actual_times, SOURCE_FRAMES * sizeof(uint32_t));
}
