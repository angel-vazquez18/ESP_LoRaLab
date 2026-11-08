#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define NODE_RECORD_BYTES 4096
#define NODE_REPLY_SLOTS 4
#define NODE_EVENT_SLOTS 8
#define NODE_CACHE_SLOTS 16
#define NODE_PROBE_BYTES 65536
#define NODE_OPERATION_US 30000000LL

typedef struct {
    uint64_t free_bytes, minimum_free_bytes, largest_free_bytes;
    bool present;
} node_heap;

typedef struct {
    void *context;
    int64_t (*now_us)(void *);
    bool (*sha256)(void *, const void *, size_t, uint8_t[32]);
    void (*random_bytes)(void *, void *, size_t);
    void *(*allocate)(void *, size_t);
    void (*deallocate)(void *, void *);
    void (*memory)(void *, node_heap *, node_heap *, uint32_t *);
    const char *device_id, *boot_id, *firmware_version, *firmware_build_id;
    const char *idf_version, *board_manifest_hash, *schema_sha256, *reset_cause;
} node_platform;

typedef struct node_control node_control;
node_control *node_control_create(const node_platform *platform);
void node_control_destroy(node_control *node);
void node_control_feed(node_control *node, const uint8_t *bytes, size_t length);
void node_control_tick(node_control *node);
void node_control_link(node_control *node, bool connected);
// Returns one whole record including LF. Callers serialize all physical writes.
size_t node_control_output(node_control *node, char *destination, size_t capacity);
