#include <string.h>
#include "codec2_dependency.h"
#include "audio/codec_clip.h"

struct codec_clip {
    codec_clip_port port;
    artifact_store *store;
    codec2_clip_state *state;
    const uint8_t *input;
    uint8_t *output;
    codec_clip_status status;
};

void codec_clip_destroy(codec_clip **owner)
{
    if (!owner || !*owner) return;
    codec_clip *clip = *owner;
    codec2_clip_destroy(clip->state);
    if (!clip->status.complete && clip->output)
        artifact_store_delete(clip->store, clip->status.output_id);
    artifact_store_release(clip->store, clip->status.source_id);
    codec_clip_port port = clip->port;
    memset(clip, 0, sizeof(*clip));
    port.deallocate(port.context, clip);
    *owner = NULL;
}

artifact_status codec_clip_create(artifact_store *store, const char *owner,
    const char *source_id, const char *output_id, bool decoding, codec_clip_port port, codec_clip **output)
{
    if (!store || !owner || !output || !port.allocate || !port.deallocate || !port.sha256 || !port.now_us ||
        !source_id || !output_id || strlen(source_id) != 36 || strlen(output_id) != 36 ||
        !strcmp(source_id, output_id)) return ARTIFACT_INVALID_ARGUMENT;
    *output = NULL;
    const artifact_manifest *source = artifact_store_find(store, source_id);
    if (!source) return ARTIFACT_NOT_FOUND;
    if (decoding) {
        if (strcmp(source->format, "codec2_3200_v1") || !source->sample_count || source->sample_count > 24000 ||
            source->frame_count != (source->sample_count + 159) / 160 ||
            source->length_bytes != source->frame_count * 8) return ARTIFACT_INVALID_ARGUMENT;
    } else if (strcmp(source->format, "pcm_s16le_8000_mono") || !source->length_bytes ||
        source->length_bytes % 2 || source->length_bytes > 48000) return ARTIFACT_INVALID_ARGUMENT;
    if (source->state != ARTIFACT_COMMITTED) return ARTIFACT_INVALID_STATE;
    int64_t started = port.now_us(port.context);
    codec_clip *clip = port.allocate(port.context, sizeof(*clip));
    if (!clip) return ARTIFACT_ALLOCATION_FAILED;
    memset(clip, 0, sizeof(*clip));
    clip->port = port;
    clip->store = store;
    clip->status.started_us = (uint64_t)started;
    memcpy(clip->status.source_id, source_id, 37);
    memcpy(clip->status.source_sha256, source->sha256, 65);
    memcpy(clip->status.output_id, output_id, 37);
    clip->status.decoding = decoding;
    clip->status.input_samples = decoding ? source->sample_count : source->length_bytes / 2;
    clip->status.frame_count = (clip->status.input_samples + 159) / 160;
    clip->status.padded_samples = clip->status.frame_count * 160 - clip->status.input_samples;
    size_t length = 0;
    const void *input = NULL;
    artifact_status error = artifact_store_acquire(store, source_id, &input, &length);
    if (error != ARTIFACT_OK) {
        port.deallocate(port.context, clip);
        return error;
    }
    clip->input = input;
    void *destination = NULL;
    error = decoding ? artifact_store_decode_begin(store, owner, output_id, source_id,
                                        clip->status.input_samples, &destination) :
                       artifact_store_encode_begin(store, owner, output_id, source_id,
                                        clip->status.input_samples, &destination);
    if (error == ARTIFACT_OK) {
        clip->output = destination;
        clip->state = codec2_clip_create();
        if (!clip->state) error = ARTIFACT_ALLOCATION_FAILED;
    }
    int64_t ended = port.now_us(port.context);
    if (ended < started) error = ARTIFACT_INTERNAL_ERROR;
    if (error != ARTIFACT_OK) {
        codec_clip_destroy(&clip);
        return error;
    }
    clip->status.setup_us = (uint64_t)(ended - started);
    *output = clip;
    return ARTIFACT_OK;
}

void codec_clip_step(codec_clip *clip)
{
    if (!clip || clip->status.complete || clip->status.error) return;
    codec_clip_status *status = &clip->status;
    int64_t started = clip->port.now_us(clip->port.context);
    if (status->frames_completed < status->frame_count) {
        short samples[160] = {0};
        uint32_t offset = status->frames_completed * 160;
        for (unsigned i = 0; !status->decoding && i < 160 && offset + i < status->input_samples; i++) {
            unsigned value = clip->input[(offset + i) * 2] |
                             (unsigned)clip->input[(offset + i) * 2 + 1] << 8;
            samples[i] = (short)(value >= 32768 ? (int)value - 65536 : (int)value);
        }
        int64_t call_start = clip->port.now_us(clip->port.context);
        if (call_start < started) { status->error = ARTIFACT_INTERNAL_ERROR; return; }
        status->conversion_us += (uint64_t)(call_start - started);
        bool converted = status->decoding ?
            codec2_decode_frame(clip->state, clip->input + status->encoded_bytes, 8, samples, 160) :
            codec2_encode_frame(clip->state, samples, 160, clip->output + status->encoded_bytes, 8);
        int64_t ended = clip->port.now_us(clip->port.context);
        if (!converted || ended < call_start) { status->error = ARTIFACT_INTERNAL_ERROR; return; }
        status->codec_us += (uint64_t)(ended - call_start);
        uint32_t count = status->input_samples - offset;
        if (count > 160) count = 160;
        if (status->decoding) {
            for (unsigned i = 0; i < count; i++) {
                uint16_t value = (uint16_t)samples[i];
                clip->output[(offset + i) * 2] = value & 255;
                clip->output[(offset + i) * 2 + 1] = value >> 8;
            }
            int64_t copied = clip->port.now_us(clip->port.context);
            if (copied < ended) { status->error = ARTIFACT_INTERNAL_ERROR; return; }
            status->conversion_us += (uint64_t)(copied - ended);
        }
        status->samples_completed += count;
        status->frames_completed++;
        status->encoded_bytes += 8;
        return;
    }
    status->error = status->decoding ?
        artifact_store_capture_finish(clip->store, status->output_id, status->input_samples,
                                     clip->port.sha256, clip->port.context) :
        artifact_store_encode_finish(clip->store, status->output_id, clip->port.sha256, clip->port.context);
    int64_t ended = clip->port.now_us(clip->port.context);
    if (ended < started) status->error = ARTIFACT_INTERNAL_ERROR;
    else status->finalize_us = (uint64_t)(ended - started);
    status->complete = status->error == ARTIFACT_OK;
}

codec_clip_status codec_clip_progress(const codec_clip *clip)
{
    return clip ? clip->status : (codec_clip_status){.error = ARTIFACT_INVALID_STATE};
}

void codec_clip_memory(const codec_clip *s, node_memory_inventory *out)
{
    if (!s) return;
    node_memory_add(out, "codec_clip_owner", s, sizeof(*s));
    node_memory_add(out, "codec_state", s->state, codec2_clip_state_bytes());
}
