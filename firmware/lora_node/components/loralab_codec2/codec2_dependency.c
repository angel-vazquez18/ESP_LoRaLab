#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#if defined(CONFIG_LORALAB_CODEC2) && CONFIG_ESP_MAIN_TASK_STACK_SIZE < 32768
#error "Codec 2 requires CONFIG_ESP_MAIN_TASK_STACK_SIZE >= 32768; update sdkconfig before building"
#endif
#endif

#include "codec2_dependency.h"
#include "codec2.h"
#include "codec2_internal.h"

_Static_assert(sizeof(short) == 2 && sizeof(float) == 4, "Codec sample/arithmetic format");

bool codec2_dependency_query(unsigned mode, codec2_frame_format *format)
{
    if (!format)
        return false;
    *format = (codec2_frame_format){0};
    if (mode != 3200)
        return false;
    struct CODEC2 *state = codec2_create(CODEC2_MODE_3200);
    if (!state)
        return false;
    int samples = codec2_samples_per_frame(state);
    int bits = codec2_bits_per_frame(state);
    int bytes = codec2_bytes_per_frame(state);
    codec2_destroy(state);
    if (samples != 160 || bits != 64 || bytes != 8)
        return false;
    *format = (codec2_frame_format){samples, bits, bytes, 8000};
    return true;
}

const char *codec2_dependency_version(void) { return CODEC2_VERSION; }
const char *codec2_dependency_revision(void)
{
    return "06d4c11e699b0351765f10398abb4f663a984f36";
}

codec2_clip_state *codec2_clip_create(void) { return codec2_create(CODEC2_MODE_3200); }

bool codec2_encode_frame(codec2_clip_state *state, short *samples, size_t sample_count,
                          uint8_t *output, size_t capacity)
{
    if (!state || !samples || sample_count != 160 || !output || capacity < 8)
        return false;
    codec2_encode(state, output, samples);
    return true;
}

bool codec2_decode_frame(codec2_clip_state *state, const uint8_t *input, size_t length,
                          short *output, size_t sample_capacity)
{
    if (!state || !input || length != 8 || !output || sample_capacity < 160)
        return false;
    codec2_decode(state, output, input);
    return true;
}

void codec2_clip_destroy(codec2_clip_state *state)
{
    if (state) codec2_destroy(state);
}

size_t codec2_clip_state_bytes(void) { return sizeof(struct CODEC2); }
