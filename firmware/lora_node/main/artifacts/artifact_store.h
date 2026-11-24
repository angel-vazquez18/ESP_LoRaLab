#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "generated/artifact_profile.h"

typedef enum { ARTIFACT_UPLOADING, ARTIFACT_FAILED, ARTIFACT_COMMITTED } artifact_state;
typedef enum {
    ARTIFACT_OK,
    ARTIFACT_INVALID_ARGUMENT,
    ARTIFACT_RESOURCE_LIMIT,
    ARTIFACT_ALLOCATION_FAILED,
    ARTIFACT_NOT_FOUND,
    ARTIFACT_INVALID_STATE,
    ARTIFACT_BUSY,
    ARTIFACT_OFFSET_MISMATCH,
    ARTIFACT_CHECKSUM_MISMATCH,
    ARTIFACT_INTERNAL_ERROR
} artifact_status;

typedef struct {
    const char *artifact_id, *kind, *sha256, *format;
    size_t length_bytes;
} artifact_spec;

typedef struct {
    char artifact_id[37], kind[10], sha256[65], format[21];
    size_t length_bytes, next_offset;
    char source_artifact_id[37];
    uint32_t sample_count, frame_count;
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

// Preflight keeps reply allocation failures from advancing an upload.
artifact_status artifact_store_check_put(artifact_store *store, const char *id, size_t offset,
                                        const void *bytes, size_t length, uint32_t crc);
artifact_status artifact_store_put(artifact_store *store, const char *id, size_t offset,
                                  const void *bytes, size_t length, uint32_t crc);

// Verification is private until its correlated reply has been admitted.
artifact_status artifact_store_prepare_commit(artifact_store *store, const char *id,
    bool (*sha256)(void *, const void *, size_t, uint8_t[32]), void *context);
void artifact_store_accept_commit(artifact_store *store, const char *id);

artifact_status artifact_store_get(const artifact_store *store, const char *id, size_t offset,
                                   void *output, size_t requested, size_t *length, bool *eof);

// A finite hardware producer fills this private reservation; only finish publishes it.
artifact_status artifact_store_capture_begin(artifact_store *store, const char *owner,
    const char *id, uint32_t samples, void **destination);
artifact_status artifact_store_capture_finish(artifact_store *store, const char *id,
    uint32_t samples, bool (*sha256)(void *, const void *, size_t, uint8_t[32]), void *context);

// Local derived output stays private until all frames and its final hash exist.
artifact_status artifact_store_encode_begin(artifact_store *store, const char *owner,
    const char *id, const char *source_id, uint32_t samples, void **destination);
artifact_status artifact_store_decode_begin(artifact_store *store, const char *owner,
    const char *id, const char *source_id, uint32_t samples, void **destination);
// Authenticated RF reconstruction is the only external encoded producer.
artifact_status artifact_store_recover_encoded_begin(artifact_store *store, const char *owner,
    const char *id, const char *source_id, uint32_t samples, const char *sha256, void **destination);
artifact_status artifact_store_encode_finish(artifact_store *store, const char *id,
    bool (*sha256)(void *, const void *, size_t, uint8_t[32]), void *context);
