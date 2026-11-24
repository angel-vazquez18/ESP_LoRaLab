#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "memory/buffers.h"

#define SOURCE_FRAME_BYTES 8U
#define SOURCE_FRAME_US 20000U
#define SOURCE_MESSAGE_BYTES 1200U
#define SOURCE_QUEUE_BYTES 4800U
#define SOURCE_FRAMES 3000U
#define SOURCE_MESSAGES 20U
#define SOURCE_DURATION_US 60000000LL
#define SOURCE_MAX_DRAIN_US 30000000U

#define SOURCE_COUNTERS(X)                                                                         \
    X(phase)                                                                                       \
    X(frames_produced) X(frames_missed) X(frames_cancelled) X(produced_bytes) X(admitted_bytes)    \
        X(overflow_dropped_bytes) X(admitted_messages) X(dropped_messages) X(taken_messages)       \
            X(sent_messages) X(failed_messages) X(sent_bytes) X(failed_bytes)                      \
                X(consumer_discarded_bytes) X(queue_discarded_messages) X(queue_discarded_bytes)   \
                    X(partial_discarded_bytes) X(ready_messages) X(partial_bytes) X(active_bytes)  \
                        X(occupancy_bytes) X(peak_occupancy_bytes) X(late_frames)                  \
                            X(max_lateness_us) X(trace_frames) X(admitted_message_mask)            \
                                X(overflow_message_mask) X(sent_message_mask)                      \
                                    X(failed_message_mask) X(discarded_message_mask)

typedef enum
{
    SOURCE_PREPARED,
    SOURCE_PRODUCING,
    SOURCE_DRAINING,
    SOURCE_FINISHED,
    SOURCE_CANCELLED
} encoded_source_phase;
typedef struct
{
    void *context;
    void *(*allocate)(void *, size_t);
    void (*release)(void *, void *);
} encoded_source_memory;
typedef struct encoded_queue encoded_queue;
typedef struct
{
    int64_t started_us, production_end_us, drain_deadline_us;
#define FIELD(name) uint32_t name;
    SOURCE_COUNTERS(FIELD)
#undef FIELD
    bool drain_cutoff, consistent, cancel_requested;
} encoded_source_status;
typedef struct
{
    uint32_t message_id;
    const uint8_t *data;
    size_t length;
} encoded_source_message;
typedef enum
{
    SOURCE_SENT,
    SOURCE_FAILED,
    SOURCE_DISCARDED
} encoded_source_outcome;
typedef struct
{
    uint32_t index, planned_elapsed_us, actual_elapsed_us;
    bool produced;
} encoded_source_trace;

#define SOURCE_AUDIT_ROWS 451U
#define SOURCE_AUDIT_US 200000U
typedef struct
{
    uint32_t index, planned_elapsed_us, actual_elapsed_us, missed_intervals;
    encoded_source_status status;
} encoded_source_sample;

encoded_queue *encoded_queue_create(encoded_source_memory, const void *reference, size_t bytes,
                                    uint32_t drain_us);
bool encoded_queue_start(encoded_queue *, int64_t start_us);
// Single producer; timing is independent of consumer/radio progress.
void encoded_queue_step(encoded_queue *, int64_t now_us);
void encoded_queue_snapshot(const encoded_queue *, encoded_source_status *);
// One consumer borrows one immutable whole message, retaining it across retries.
bool encoded_queue_take(encoded_queue *, encoded_source_message *);
// Complete only after the consumer/radio no longer uses the borrowed bytes.
bool encoded_queue_complete(encoded_queue *, uint32_t message_id, encoded_source_outcome);
size_t encoded_queue_trace(const encoded_queue *, uint32_t first, encoded_source_trace *,
                           size_t count);
size_t encoded_queue_samples(const encoded_queue *, uint32_t first, encoded_source_sample *,
                             size_t count);
void encoded_queue_request_stop(encoded_queue *);
// Caller must confirm producer/consumer quiescence before retiring or destroying.
bool encoded_queue_retire_payload(encoded_queue *);
void encoded_queue_destroy(encoded_queue *);
void encoded_queue_memory(const encoded_queue *, node_memory_inventory *);
