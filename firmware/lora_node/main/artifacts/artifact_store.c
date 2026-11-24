#include <stdlib.h>
#include <string.h>

#include "artifact_store.h"
#include "protocol/chunk_bytes.h"

typedef struct {
    artifact_manifest manifest;
    char owner[37];
    void *bytes;
    bool commit_prepared, producing;
    artifact_status commit_result;
} artifact_slot;

struct artifact_store {
    void *context;
    void *(*allocate)(void *, size_t);
    void (*deallocate)(void *, void *);
    size_t reserved_bytes;
    artifact_slot slots[ARTIFACT_SLOTS];
};

static bool equal(const char *a, const char *b) { return a && b && !strcmp(a, b); }
static bool hex_string(const char *value, size_t length, bool uuid)
{
    if (!value || strlen(value) != length)
        return false;
    for (size_t i = 0; i < length; i++) {
        if (uuid && (i == 8 || i == 13 || i == 18 || i == 23)) {
            if (value[i] != '-')
                return false;
        } else if (!((value[i] >= '0' && value[i] <= '9') ||
                     (value[i] >= 'a' && value[i] <= 'f')))
            return false;
    }
    return true;
}
static artifact_slot *find(artifact_store *s, const char *id)
{
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++)
        if (s->slots[i].bytes && equal(s->slots[i].manifest.artifact_id, id))
            return &s->slots[i];
    return NULL;
}
static void clear(artifact_store *s, artifact_slot *slot)
{
    if (!slot->bytes)
        return;
    s->deallocate(s->context, slot->bytes);
    s->reserved_bytes -= slot->manifest.length_bytes;
    memset(slot, 0, sizeof(*slot));
}

artifact_store *artifact_store_create(void *context, void *(*allocate)(void *, size_t),
                                      void (*deallocate)(void *, void *))
{
    if (!allocate || !deallocate)
        return NULL;
    artifact_store *s = calloc(1, sizeof(*s));
    if (s) {
        s->context = context;
        s->allocate = allocate;
        s->deallocate = deallocate;
    }
    return s;
}
void artifact_store_destroy(artifact_store *s)
{
    if (!s)
        return;
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++)
        clear(s, &s->slots[i]);
    free(s);
}
static artifact_status reserve(artifact_store *s, const char *owner,
                                     const artifact_spec *spec, bool encoded)
{
    if (!spec || !hex_string(owner, 36, true) ||
        !hex_string(spec->artifact_id, 36, true) || !hex_string(spec->sha256, 64, false) ||
        (!equal(spec->kind, "source") && !equal(spec->kind, "recovered")) ||
        (!equal(spec->format, "known_data") && !equal(spec->format, "pcm_s16le_8000_mono") &&
         !(encoded && equal(spec->format, "codec2_3200_v1"))) ||
        !spec->length_bytes)
        return ARTIFACT_INVALID_ARGUMENT;
    if (spec->length_bytes > ARTIFACT_MAX_BYTES)
        return ARTIFACT_RESOURCE_LIMIT;
    if (equal(spec->format, "pcm_s16le_8000_mono") &&
        (spec->length_bytes % 2 || spec->length_bytes > 48000))
        return ARTIFACT_INVALID_ARGUMENT;
    if (find(s, spec->artifact_id))
        return ARTIFACT_INVALID_STATE;
    if (spec->length_bytes > ARTIFACT_TOTAL_BYTES - s->reserved_bytes)
        return ARTIFACT_RESOURCE_LIMIT;
    artifact_slot *slot = NULL;
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++)
        if (!s->slots[i].bytes) {
            slot = &s->slots[i];
            break;
        }
    if (!slot)
        return ARTIFACT_RESOURCE_LIMIT;
    void *bytes = s->allocate(s->context, spec->length_bytes);
    if (!bytes)
        return ARTIFACT_ALLOCATION_FAILED;
    // Publish metadata only after the full reservation succeeds.
    artifact_manifest *m = &slot->manifest;
    memcpy(m->artifact_id, spec->artifact_id, sizeof(m->artifact_id));
    memcpy(m->kind, spec->kind, strlen(spec->kind) + 1);
    memcpy(m->format, spec->format, strlen(spec->format) + 1);
    memcpy(m->sha256, spec->sha256, sizeof(m->sha256));
    memcpy(slot->owner, owner, sizeof(slot->owner));
    m->length_bytes = spec->length_bytes;
    m->next_offset = 0;
    m->state = ARTIFACT_UPLOADING;
    m->in_use = false;
    slot->bytes = bytes;
    s->reserved_bytes += spec->length_bytes;
    return ARTIFACT_OK;
}
artifact_status artifact_store_begin(artifact_store *s, const char *owner,
                                     const artifact_spec *spec)
{
    return reserve(s, owner, spec, false);
}
const artifact_manifest *artifact_store_find(const artifact_store *s, const char *id)
{
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++)
        if (s->slots[i].bytes && equal(s->slots[i].manifest.artifact_id, id))
            return &s->slots[i].manifest;
    return NULL;
}
const artifact_manifest *artifact_store_at(const artifact_store *s, unsigned slot)
{
    return slot < ARTIFACT_SLOTS && s->slots[slot].bytes ? &s->slots[slot].manifest : NULL;
}
size_t artifact_store_reserved_bytes(const artifact_store *s) { return s->reserved_bytes; }
artifact_status artifact_store_delete(artifact_store *s, const char *id)
{
    artifact_slot *slot = find(s, id);
    if (!slot)
        return ARTIFACT_NOT_FOUND;
    if (slot->manifest.in_use)
        return ARTIFACT_BUSY;
    clear(s, slot);
    return ARTIFACT_OK;
}
void artifact_store_release_owner(artifact_store *s, const char *owner)
{
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++) {
        artifact_slot *slot = &s->slots[i];
        if (slot->bytes && slot->manifest.state != ARTIFACT_COMMITTED && equal(slot->owner, owner))
            clear(s, slot);
    }
}
artifact_status artifact_store_acquire(artifact_store *s, const char *id,
                                       const void **bytes, size_t *length)
{
    if (!bytes || !length)
        return ARTIFACT_INVALID_ARGUMENT;
    *bytes = NULL;
    *length = 0;
    artifact_slot *slot = find(s, id);
    if (!slot)
        return ARTIFACT_NOT_FOUND;
    if (slot->manifest.state != ARTIFACT_COMMITTED)
        return ARTIFACT_INVALID_STATE;
    if (slot->manifest.in_use)
        return ARTIFACT_BUSY;
    slot->manifest.in_use = true;
    *bytes = slot->bytes;
    *length = slot->manifest.length_bytes;
    return ARTIFACT_OK;
}
void artifact_store_release(artifact_store *s, const char *id)
{
    artifact_slot *slot = find(s, id);
    if (slot)
        slot->manifest.in_use = false;
}

artifact_status artifact_store_check_put(artifact_store *s, const char *id, size_t offset,
                                        const void *bytes, size_t length, uint32_t crc)
{
    if (!bytes || !length || length > ARTIFACT_CHUNK_BYTES)
        return ARTIFACT_INVALID_ARGUMENT;
    artifact_slot *slot = find(s, id);
    if (!slot) return ARTIFACT_NOT_FOUND;
    artifact_manifest *m = &slot->manifest;
    if (slot->producing || m->state != ARTIFACT_UPLOADING) return ARTIFACT_INVALID_STATE;
    if (chunk_crc32(bytes, length) != crc) return ARTIFACT_CHECKSUM_MISMATCH;
    if (offset > m->next_offset || offset > m->length_bytes || length > m->length_bytes - offset)
        return ARTIFACT_OFFSET_MISMATCH;
    if (offset < m->next_offset &&
        (length > m->next_offset - offset || memcmp((uint8_t *)slot->bytes + offset, bytes, length)))
        return ARTIFACT_OFFSET_MISMATCH;
    return ARTIFACT_OK;
}
artifact_status artifact_store_put(artifact_store *s, const char *id, size_t offset,
                                  const void *bytes, size_t length, uint32_t crc)
{
    artifact_status result = artifact_store_check_put(s, id, offset, bytes, length, crc);
    if (result != ARTIFACT_OK) return result;
    artifact_slot *slot = find(s, id);
    if (offset == slot->manifest.next_offset) {
        memcpy((uint8_t *)slot->bytes + offset, bytes, length);
        slot->manifest.next_offset += length;
        slot->commit_prepared = false;
    }
    return ARTIFACT_OK;
}

artifact_status artifact_store_prepare_commit(artifact_store *s, const char *id,
    bool (*sha256)(void *, const void *, size_t, uint8_t[32]), void *context)
{
    artifact_slot *slot = find(s, id);
    if (!slot) return ARTIFACT_NOT_FOUND;
    slot->commit_prepared = false;
    artifact_manifest *m = &slot->manifest;
    if (m->state == ARTIFACT_COMMITTED) return ARTIFACT_OK;
    if (slot->producing || m->state != ARTIFACT_UPLOADING || m->next_offset != m->length_bytes)
        return ARTIFACT_INVALID_STATE;
    uint8_t digest[32];
    if (!sha256 || !sha256(context, slot->bytes, m->length_bytes, digest))
        return ARTIFACT_INTERNAL_ERROR;
    static const char hex[] = "0123456789abcdef";
    bool matches = true;
    for (unsigned i = 0; i < sizeof(digest); i++)
        if (m->sha256[i * 2] != hex[digest[i] >> 4] ||
            m->sha256[i * 2 + 1] != hex[digest[i] & 15]) matches = false;
    slot->commit_result = matches ? ARTIFACT_OK : ARTIFACT_CHECKSUM_MISMATCH;
    slot->commit_prepared = true;
    return slot->commit_result;
}
void artifact_store_accept_commit(artifact_store *s, const char *id)
{
    artifact_slot *slot = find(s, id);
    if (slot && slot->commit_prepared) {
        slot->manifest.state = slot->commit_result == ARTIFACT_OK ? ARTIFACT_COMMITTED : ARTIFACT_FAILED;
        slot->commit_prepared = false;
    }
}

artifact_status artifact_store_get(const artifact_store *s, const char *id, size_t offset,
                                   void *output, size_t requested, size_t *length, bool *eof)
{
    if (!output || !length || !eof || !requested || requested > ARTIFACT_CHUNK_BYTES)
        return ARTIFACT_INVALID_ARGUMENT;
    *length = 0;
    *eof = false;
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++) {
        const artifact_slot *slot = &s->slots[i];
        if (!slot->bytes || !equal(slot->manifest.artifact_id, id)) continue;
        const artifact_manifest *m = &slot->manifest;
        if (m->state != ARTIFACT_COMMITTED) return ARTIFACT_INVALID_STATE;
        if (offset > m->length_bytes) return ARTIFACT_OFFSET_MISMATCH;
        *length = m->length_bytes - offset;
        if (*length > requested) *length = requested;
        memcpy(output, (const uint8_t *)slot->bytes + offset, *length);
        *eof = offset + *length == m->length_bytes;
        return ARTIFACT_OK;
    }
    return ARTIFACT_NOT_FOUND;
}

artifact_status artifact_store_capture_begin(artifact_store *s, const char *owner,
    const char *id, uint32_t samples, void **destination)
{
    if (!destination || !samples || samples > 24000) return ARTIFACT_INVALID_ARGUMENT;
    artifact_spec spec = {.artifact_id = id, .kind = "source", .format = "pcm_s16le_8000_mono",
        .length_bytes = samples * 2, .sha256 = "0000000000000000000000000000000000000000000000000000000000000000"};
    artifact_status status = artifact_store_begin(s, owner, &spec);
    if (status != ARTIFACT_OK) return status;
    artifact_slot *slot = find(s, id);
    slot->producing = true;
    *destination = slot->bytes;
    return ARTIFACT_OK;
}
static artifact_status finish_producer(artifact_store *s, const char *id,
    bool (*sha256)(void *, const void *, size_t, uint8_t[32]), void *context)
{
    artifact_slot *slot = find(s, id);
    if (!sha256 || !slot || !slot->producing || slot->manifest.state != ARTIFACT_UPLOADING)
        return ARTIFACT_INVALID_STATE;
    uint8_t digest[32];
    if (!sha256(context, slot->bytes, slot->manifest.length_bytes, digest)) return ARTIFACT_INTERNAL_ERROR;
    static const char hex[] = "0123456789abcdef";
    for (unsigned i = 0; i < 32; i++) {
        slot->manifest.sha256[i * 2] = hex[digest[i] >> 4];
        slot->manifest.sha256[i * 2 + 1] = hex[digest[i] & 15];
    }
    slot->manifest.sha256[64] = 0;
    slot->manifest.next_offset = slot->manifest.length_bytes;
    slot->manifest.state = ARTIFACT_COMMITTED;
    slot->producing = false;
    return ARTIFACT_OK;
}

artifact_status artifact_store_capture_finish(artifact_store *s, const char *id,
    uint32_t samples, bool (*sha256)(void *, const void *, size_t, uint8_t[32]), void *context)
{
    artifact_slot *slot = find(s, id);
    if (!slot || !samples || samples > 24000 || samples * 2 != slot->manifest.length_bytes ||
        !equal(slot->manifest.format, "pcm_s16le_8000_mono")) return ARTIFACT_INVALID_STATE;
    return finish_producer(s, id, sha256, context);
}
artifact_status artifact_store_encode_begin(artifact_store *s, const char *owner,
    const char *id, const char *source_id, uint32_t samples, void **destination)
{
    if (!destination || !samples || samples > 24000 || !hex_string(source_id, 36, true) ||
        equal(source_id, id)) return ARTIFACT_INVALID_ARGUMENT;
    uint32_t frames = (samples + 159) / 160;
    artifact_spec spec = {.artifact_id = id, .kind = "source", .format = "codec2_3200_v1",
        .length_bytes = frames * 8,
        .sha256 = "0000000000000000000000000000000000000000000000000000000000000000"};
    artifact_status status = reserve(s, owner, &spec, true);
    if (status != ARTIFACT_OK) return status;
    artifact_slot *slot = find(s, id);
    slot->producing = true;
    memcpy(slot->manifest.source_artifact_id, source_id, 37);
    slot->manifest.sample_count = samples;
    slot->manifest.frame_count = frames;
    *destination = slot->bytes;
    return ARTIFACT_OK;
}
artifact_status artifact_store_decode_begin(artifact_store *s, const char *owner,
    const char *id, const char *source_id, uint32_t samples, void **destination)
{
    if (!destination || !samples || samples > 24000 || !hex_string(source_id, 36, true) ||
        equal(source_id, id)) return ARTIFACT_INVALID_ARGUMENT;
    artifact_spec spec = {.artifact_id = id, .kind = "recovered", .format = "pcm_s16le_8000_mono",
        .length_bytes = samples * 2,
        .sha256 = "0000000000000000000000000000000000000000000000000000000000000000"};
    artifact_status status = artifact_store_begin(s, owner, &spec);
    if (status != ARTIFACT_OK) return status;
    artifact_slot *slot = find(s, id);
    slot->producing = true;
    memcpy(slot->manifest.source_artifact_id, source_id, 37);
    *destination = slot->bytes;
    return ARTIFACT_OK;
}
artifact_status artifact_store_recover_encoded_begin(artifact_store *s, const char *owner,
    const char *id, const char *source_id, uint32_t samples, const char *sha256, void **destination)
{
    if (!destination || !samples || samples > 24000 || !hex_string(source_id, 36, true) ||
        !hex_string(sha256, 64, false) || equal(source_id, id)) return ARTIFACT_INVALID_ARGUMENT;
    artifact_spec spec = {id, "recovered", sha256, "codec2_3200_v1", ((samples + 159) / 160) * 8};
    artifact_status status = reserve(s, owner, &spec, true);
    if (status != ARTIFACT_OK) return status;
    artifact_slot *slot = find(s, id);
    slot->producing = true;
    memcpy(slot->manifest.source_artifact_id, source_id, 37);
    slot->manifest.sample_count = samples;
    slot->manifest.frame_count = (samples + 159) / 160;
    *destination = slot->bytes;
    return ARTIFACT_OK;
}
artifact_status artifact_store_encode_finish(artifact_store *s, const char *id,
    bool (*sha256)(void *, const void *, size_t, uint8_t[32]), void *context)
{
    artifact_slot *slot = find(s, id);
    if (!slot || !equal(slot->manifest.format, "codec2_3200_v1")) return ARTIFACT_INVALID_STATE;
    return finish_producer(s, id, sha256, context);
}

void artifact_store_memory(const artifact_store *s, node_memory_inventory *out)
{
    if (!s) return;
    node_memory_add(out, "artifact_store", s, sizeof(*s));
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++) {
        const char *names[] = {"artifact_slot_0", "artifact_slot_1", "artifact_slot_2", "artifact_slot_3"};
        node_memory_add(out, names[i], s->slots[i].bytes, s->slots[i].manifest.length_bytes);
    }
}
