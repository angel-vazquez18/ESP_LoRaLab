#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "generated/memory_profile.h"

#define MEMORY_BUFFER_LIMIT MEMORY_MAX_BUFFERS
#define MEMORY_BUFFER_NAME 24U

typedef enum { MEMORY_UNKNOWN, MEMORY_INTERNAL, MEMORY_PSRAM } node_memory_region;
typedef struct {
    char name[MEMORY_BUFFER_NAME];
    const void *pointer; // Never serialized.
    size_t requested_bytes;
    node_memory_region region;
} node_memory_buffer;
typedef struct {
    node_memory_buffer items[MEMORY_BUFFER_LIMIT];
    unsigned count, aliases_omitted;
    bool truncated, overlap;
} node_memory_inventory;

static inline void node_memory_add(node_memory_inventory *out, const char *name,
                                    const void *pointer, size_t bytes)
{
    if (!pointer || !bytes) return;
    uintptr_t start = (uintptr_t)pointer;
    if (!name || strlen(name) >= MEMORY_BUFFER_NAME || bytes > UINTPTR_MAX - start) {
        out->truncated = true;
        return;
    }
    for (unsigned i = 0; i < out->count; i++) {
        const node_memory_buffer *previous = &out->items[i];
        uintptr_t other = (uintptr_t)previous->pointer;
        if (start == other && bytes == previous->requested_bytes) {
            out->aliases_omitted++;
            return;
        }
        if (start < other + previous->requested_bytes && other < start + bytes) {
            out->overlap = true;
            return; // Do not double-count intersecting ownership claims.
        }
    }
    if (out->count == MEMORY_BUFFER_LIMIT) { out->truncated = true; return; }
    node_memory_buffer *entry = &out->items[out->count++];
    memcpy(entry->name, name, strlen(name) + 1);
    entry->pointer = pointer;
    entry->requested_bytes = bytes;
    entry->region = MEMORY_UNKNOWN;
}
