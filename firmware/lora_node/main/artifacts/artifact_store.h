#pragma once
#include <stdbool.h>
#include <stddef.h>

#include "generated/artifact_profile.h"

typedef enum { ARTIFACT_UPLOADING, ARTIFACT_FAILED, ARTIFACT_COMMITTED } artifact_state;
typedef enum {
    ARTIFACT_OK,
    ARTIFACT_INVALID_ARGUMENT,
    ARTIFACT_RESOURCE_LIMIT,
    ARTIFACT_ALLOCATION_FAILED,
    ARTIFACT_NOT_FOUND,
    ARTIFACT_INVALID_STATE,
    ARTIFACT_BUSY
} artifact_status;

typedef struct {
    const char *artifact_id, *kind, *sha256, *format;
    size_t length_bytes;
} artifact_spec;

typedef struct {
    char artifact_id[37], kind[10], sha256[65], format[21];
    size_t length_bytes, next_offset;
    artifact_state state;
    bool in_use;
} artifact_manifest;

typedef struct artifact_store artifact_store;
artifact_store *artifact_store_create(void *context, void *(*allocate)(void *, size_t),
                                      void (*deallocate)(void *, void *));
void artifact_store_destroy(artifact_store *store);
artifact_status artifact_store_begin(artifact_store *store, const char *owner,
                                     const artifact_spec *spec);
const artifact_manifest *artifact_store_find(const artifact_store *store, const char *id);
const artifact_manifest *artifact_store_at(const artifact_store *store, unsigned slot);
size_t artifact_store_reserved_bytes(const artifact_store *store);
artifact_status artifact_store_delete(artifact_store *store, const char *id);
void artifact_store_release_owner(artifact_store *store, const char *owner);

// Consumers borrow only committed bytes and must release them before deletion.
artifact_status artifact_store_acquire(artifact_store *store, const char *id,
                                       const void **bytes, size_t *length);
void artifact_store_release(artifact_store *store, const char *id);
