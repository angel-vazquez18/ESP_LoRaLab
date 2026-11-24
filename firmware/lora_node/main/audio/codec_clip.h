#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "artifacts/artifact_store.h"

typedef struct codec_clip codec_clip;
typedef struct {
    void *context;
    void *(*allocate)(void *, size_t);
    void (*deallocate)(void *, void *);
    bool (*sha256)(void *, const void *, size_t, uint8_t[32]);
    int64_t (*now_us)(void *);
} codec_clip_port;
typedef struct {
    char source_id[37], source_sha256[65], output_id[37];
    uint32_t input_samples, frame_count, frames_completed, encoded_bytes, padded_samples, samples_completed;
    uint64_t started_us, setup_us, conversion_us, codec_us, finalize_us;
    bool complete, decoding;
    artifact_status error;
} codec_clip_status;

artifact_status codec_clip_create(artifact_store *store, const char *owner,
    const char *source_id, const char *output_id, bool decoding, codec_clip_port port, codec_clip **output);
void codec_clip_step(codec_clip *clip); // At most one 160-sample frame per call.
codec_clip_status codec_clip_progress(const codec_clip *clip);
void codec_clip_destroy(codec_clip **clip); // Discards uncommitted output and releases input.
