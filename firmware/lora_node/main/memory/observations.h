#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "cJSON.h"
#include "memory/buffers.h"

typedef struct {
    uint64_t free_bytes, minimum_free_bytes, largest_free_bytes;
    bool present;
} node_heap;

typedef struct {
    void *context;
    int64_t (*now_us)(void *);
    void (*memory)(void *, node_heap *, node_heap *, uint32_t *);
    bool (*emit)(void *, const char *, cJSON *, const char *);
    void (*buffers)(void *, node_memory_inventory *);
} memory_observer_port;

typedef struct {
    node_memory_buffer buffer;
    uint64_t first_observed_us, generation;
} memory_track;

typedef struct {
    memory_observer_port port;
    bool active, sampled, oom, exit_sampled;
    char id[37], stage[24], workload[37], minimum_workload[37];
    uint64_t workload_samples, workload_internal, workload_psram;
    bool workload_psram_present;
    int64_t started_us, stopped_us, deadline, next_sample;
    const char *stop_reason;
    uint64_t samples, drops, missed;
    uint64_t minimum_internal, minimum_psram;
    bool psram_present;
    memory_track tracked[MEMORY_BUFFER_LIMIT];
    unsigned tracked_count;
    uint64_t generation;
} memory_observer;

void memory_observer_init(memory_observer *, memory_observer_port);
void memory_observer_start(memory_observer *, const char *id, uint32_t duration_ms,
                           const char *stage, const char *workload);
void memory_observer_tick(memory_observer *);
void memory_observer_stage(memory_observer *, const char *stage, const char *workload);
void memory_observer_leave_stage(memory_observer *);
void memory_observer_stop(memory_observer *, const char *reason);
cJSON *memory_observer_status(memory_observer *);
