#include "memory/observations.h"
#include <string.h>
#include <stdio.h>

#define PERIOD_US MEMORY_PERIOD_US

static void add(memory_observer *m, cJSON *o, const char *key, cJSON *v)
{
    if (!o || !v || !cJSON_AddItemToObject(o, key, v)) {
        cJSON_Delete(v);
        m->oom = true;
    }
}
static void number(memory_observer *m, cJSON *o, const char *key, uint64_t value)
{ add(m, o, key, cJSON_CreateNumber(value)); }
static void text(memory_observer *m, cJSON *o, const char *key, const char *value)
{ add(m, o, key, value ? cJSON_CreateString(value) : cJSON_CreateNull()); }
static cJSON *heap(memory_observer *m, node_heap value)
{
    if (!value.present) return cJSON_CreateNull();
    cJSON *o = cJSON_CreateObject();
    number(m, o, "free_bytes", value.free_bytes);
    number(m, o, "minimum_free_bytes", value.minimum_free_bytes);
    number(m, o, "largest_free_bytes", value.largest_free_bytes);
    return o;
}
static cJSON *minimum(memory_observer *m)
{
    cJSON *o = cJSON_CreateObject();
    number(m, o, "internal_free_bytes", m->minimum_internal);
    if (m->psram_present) number(m, o, "psram_free_bytes", m->minimum_psram);
    else add(m, o, "psram_free_bytes", cJSON_CreateNull());
    return o;
}
static cJSON *workload_minimum(memory_observer *m)
{
    if (!m->workload_samples) return cJSON_CreateNull();
    cJSON *o = cJSON_CreateObject(), *values = cJSON_CreateObject();
    text(m, o, "workload_id", m->minimum_workload);
    number(m, o, "samples_taken", m->workload_samples);
    number(m, values, "internal_free_bytes", m->workload_internal);
    if (m->workload_psram_present) number(m, values, "psram_free_bytes", m->workload_psram);
    else add(m, values, "psram_free_bytes", cJSON_CreateNull());
    add(m, o, "minimum", values);
    return o;
}
static void inventory(memory_observer *m, cJSON *o)
{
    node_memory_inventory current = {0};
    if (m->port.buffers) m->port.buffers(m->port.context, &current);
    memory_track previous[MEMORY_BUFFER_LIMIT];
    memcpy(previous, m->tracked, sizeof(previous));
    unsigned previous_count = m->tracked_count;
    m->tracked_count = current.count;
    uint64_t totals[3] = {0};
    cJSON *buffers = cJSON_CreateArray();
    const char *regions[] = {"unknown", "internal", "psram"};
    for (unsigned i = 0; i < current.count; i++) {
        node_memory_buffer value = current.items[i];
        if ((unsigned)value.region > MEMORY_PSRAM) value.region = MEMORY_UNKNOWN;
        memory_track tracked = {.buffer = value};
        for (unsigned j = 0; j < previous_count; j++)
            if (!strcmp(previous[j].buffer.name, value.name) &&
                previous[j].buffer.pointer == value.pointer &&
                previous[j].buffer.requested_bytes == value.requested_bytes) {
                tracked = previous[j];
                tracked.buffer = value;
                break;
            }
        if (!tracked.generation) {
            tracked.first_observed_us = m->port.now_us(m->port.context);
            tracked.generation = ++m->generation;
        }
        m->tracked[i] = tracked;
        totals[value.region] += value.requested_bytes;
        cJSON *entry = cJSON_CreateObject();
        text(m, entry, "name", value.name);
        text(m, entry, "region", regions[value.region]);
        number(m, entry, "requested_bytes", value.requested_bytes);
        number(m, entry, "first_observed_us", tracked.first_observed_us);
        number(m, entry, "generation", tracked.generation);
        if (!entry || !buffers || !cJSON_AddItemToArray(buffers, entry)) {
            cJSON_Delete(entry);
            m->oom = true;
        }
    }
    add(m, o, "known_buffers", buffers);
    cJSON *sizes = cJSON_CreateObject();
    for (unsigned i = 0; i < 3; i++) number(m, sizes, regions[i], totals[i]);
    add(m, o, "known_requested_bytes", sizes);
    number(m, o, "aliases_omitted", current.aliases_omitted);
    add(m, o, "inventory_truncated", cJSON_CreateBool(current.truncated));
    add(m, o, "overlap_detected", cJSON_CreateBool(current.overlap));
    add(m, o, "untracked_allocations", cJSON_CreateTrue());
}
static void sample(memory_observer *m, const char *reason)
{
    m->oom = false;
    int64_t taken = m->port.now_us(m->port.context);
    node_heap internal = {0}, psram = {0};
    uint32_t failures = 0;
    m->port.memory(m->port.context, &internal, &psram, &failures);
    if (!m->sampled || internal.free_bytes < m->minimum_internal)
        m->minimum_internal = internal.free_bytes;
    if (psram.present && (!m->psram_present || psram.free_bytes < m->minimum_psram))
        m->minimum_psram = psram.free_bytes;
    m->sampled = true;
    if (psram.present) m->psram_present = true;
    if (m->workload[0]) {
        if (strcmp(m->minimum_workload, m->workload)) {
            memcpy(m->minimum_workload, m->workload, 37);
            m->workload_samples = 0;
            m->workload_psram_present = false;
        }
        if (!m->workload_samples || internal.free_bytes < m->workload_internal)
            m->workload_internal = internal.free_bytes;
        if (psram.present && (!m->workload_psram_present || psram.free_bytes < m->workload_psram))
            m->workload_psram = psram.free_bytes;
        if (psram.present) m->workload_psram_present = true;
        m->workload_samples++;
    }
    cJSON *o = cJSON_CreateObject(), *memory = cJSON_CreateObject();
    text(m, o, "observation_id", m->id);
    number(m, o, "sample_index", m->samples++);
    number(m, o, "taken_us", taken);
    text(m, o, "reason", reason);
    text(m, o, "stage", m->stage);
    text(m, o, "workload_id", m->workload[0] ? m->workload : NULL);
    add(m, memory, "internal", heap(m, internal));
    add(m, memory, "psram", heap(m, psram));
    add(m, memory, "buffers", cJSON_CreateObject());
    number(m, memory, "allocation_failures", failures);
    add(m, o, "memory", memory);
    inventory(m, o);
    add(m, o, "measurement_minimum", minimum(m));
    add(m, o, "workload_minimum", workload_minimum(m));
    number(m, o, "samples_dropped", m->drops);
    number(m, o, "missed_periods", m->missed);
    number(m, o, "finished_us", m->port.now_us(m->port.context));
    if (m->oom) { cJSON_Delete(o); o = NULL; }
    if (!m->port.emit(m->port.context, "memory.sample", o, m->workload[0] ? m->workload : NULL)) m->drops++;
}
void memory_observer_init(memory_observer *m, memory_observer_port port)
{ *m = (memory_observer){.port = port}; }
void memory_observer_start(memory_observer *m, const char *id, uint32_t duration_ms,
                           const char *stage, const char *workload)
{
    memory_observer_port port = m->port;
    *m = (memory_observer){.port = port, .active = true};
    memcpy(m->id, id, 37);
    snprintf(m->stage, sizeof(m->stage), "%s", stage);
    if (workload) snprintf(m->workload, sizeof(m->workload), "%s", workload);
    int64_t now = port.now_us(port.context);
    m->started_us = now;
    m->deadline = now + (int64_t)duration_ms * 1000;
    m->next_sample = now + PERIOD_US;
    sample(m, "start");
}
void memory_observer_stop(memory_observer *m, const char *reason)
{
    if (!m->active) return;
    int64_t until = m->port.now_us(m->port.context);
    if (until > m->deadline) until = m->deadline;
    if (m->next_sample < until) {
        uint64_t missing = (until - 1 - m->next_sample) / PERIOD_US + 1;
        m->missed += missing;
        m->next_sample += (int64_t)missing * PERIOD_US;
    }
    sample(m, reason);
    m->stopped_us = m->port.now_us(m->port.context);
    m->stop_reason = reason;
    m->active = false;
}
void memory_observer_leave_stage(memory_observer *m)
{
    if (!m->active || m->exit_sampled) return;
    sample(m, "stage_exit");
    m->exit_sampled = true;
}
void memory_observer_stage(memory_observer *m, const char *stage, const char *workload)
{
    if (!m->active || (!strcmp(m->stage, stage) && !strcmp(m->workload, workload ? workload : ""))) return;
    memory_observer_leave_stage(m);
    snprintf(m->stage, sizeof(m->stage), "%s", stage);
    snprintf(m->workload, sizeof(m->workload), "%s", workload ? workload : "");
    m->exit_sampled = false;
    sample(m, "stage_entry");
}
void memory_observer_tick(memory_observer *m)
{
    if (!m->active) return;
    int64_t now = m->port.now_us(m->port.context);
    if (now >= m->deadline) { memory_observer_stop(m, "deadline"); return; }
    if (now < m->next_sample) return;
    uint64_t elapsed = (now - m->next_sample) / PERIOD_US;
    m->missed += elapsed;
    m->next_sample += (int64_t)(elapsed + 1) * PERIOD_US;
    sample(m, "periodic"); // No fabricated catch-up observations.
}
cJSON *memory_observer_status(memory_observer *m)
{
    m->oom = false;
    cJSON *o = cJSON_CreateObject();
    add(m, o, "active", cJSON_CreateBool(m->active));
    text(m, o, "observation_id", m->id[0] ? m->id : NULL);
    if (m->id[0]) {
        number(m, o, "started_us", m->started_us);
        number(m, o, "deadline_us", m->deadline);
    } else {
        add(m, o, "started_us", cJSON_CreateNull());
        add(m, o, "deadline_us", cJSON_CreateNull());
    }
    if (m->stop_reason) number(m, o, "stopped_us", m->stopped_us);
    else add(m, o, "stopped_us", cJSON_CreateNull());
    text(m, o, "stop_reason", m->stop_reason);
    number(m, o, "deadline_overrun_us", m->stopped_us > m->deadline ? m->stopped_us - m->deadline : 0);
    number(m, o, "samples_taken", m->samples);
    number(m, o, "samples_dropped", m->drops);
    number(m, o, "missed_periods", m->missed);
    add(m, o, "measurement_minimum", m->sampled ? minimum(m) : cJSON_CreateNull());
    add(m, o, "workload_minimum", workload_minimum(m));
    if (m->oom) { cJSON_Delete(o); return NULL; }
    return o;
}
