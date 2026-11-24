#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "codec2.h"
#include "codec2_dependency.h"

static int encode_reference(const char *source, const char *destination)
{
    FILE *input = fopen(source, "rb");
    FILE *output = fopen(destination, "wb");
    struct CODEC2 *state = codec2_create(CODEC2_MODE_3200);
    int result = 0;
    if (!input || !output || !state) result = 1;
    while (!result) {
        short pcm[160] = {0};
        unsigned char bits[8];
        size_t count = fread(pcm, sizeof(short), 160, input);
        if (!count) break;
        codec2_encode(state, bits, pcm);
        if (fwrite(bits, 1, 8, output) != 8) result = 2;
    }
    if (input && ferror(input)) result = 3;
    if (input) fclose(input);
    if (output && fclose(output)) result = 4;
    if (state) codec2_destroy(state);
    return result;
}

static int decode_reference(const char *source, const char *destination, const char *count_arg)
{
    char *end = NULL;
    unsigned long remaining = strtoul(count_arg, &end, 10);
    if (!end || *end || !remaining || remaining > 24000) return 5;
    FILE *input = fopen(source, "rb");
    FILE *output = fopen(destination, "wb");
    struct CODEC2 *state = codec2_create(CODEC2_MODE_3200);
    int result = (!input || !output || !state) ? 1 : 0;
    while (!result && remaining) {
        unsigned char bits[8], bytes[320];
        short pcm[160];
        if (fread(bits, 1, 8, input) != 8) { result = 2; break; }
        codec2_decode(state, pcm, bits);
        size_t samples = remaining < 160 ? remaining : 160;
        for (size_t i = 0; i < samples; i++) {
            unsigned value = (unsigned short)pcm[i];
            bytes[2 * i] = value & 255;
            bytes[2 * i + 1] = value >> 8;
        }
        if (fwrite(bytes, 2, samples, output) != samples) result = 3;
        remaining -= samples;
    }
    if (!result && (fgetc(input) != EOF || ferror(input))) result = 4;
    if (input) fclose(input);
    if (output && fclose(output)) result = 4;
    if (state) codec2_destroy(state);
    return result;
}

static int independent_states(void)
{
    codec2_clip_state *a = codec2_clip_create(), *b = codec2_clip_create(), *reference = codec2_clip_create();
    uint8_t bits[8] = {0};
    short interleaved_a[320], interleaved_b[320], isolated[320];
    int result = !a || !b || !reference;
    for (unsigned i = 0; !result && i < 2; i++) {
        if (!codec2_decode_frame(a, bits, 8, interleaved_a + i * 160, 160) ||
            !codec2_decode_frame(b, bits, 8, interleaved_b + i * 160, 160)) result = 2;
    }
    for (unsigned i = 0; !result && i < 2; i++)
        if (!codec2_decode_frame(reference, bits, 8, isolated + i * 160, 160)) result = 2;
    if (!result && (memcmp(isolated, interleaved_a, sizeof(isolated)) ||
                    memcmp(isolated, interleaved_b, sizeof(isolated)))) result = 3;
    codec2_clip_destroy(a); codec2_clip_destroy(b); codec2_clip_destroy(reference);
    return result;
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "independent-states")) return independent_states();
    if (argc == 5 && !strcmp(argv[1], "decode")) return decode_reference(argv[2], argv[3], argv[4]);
    if (argc == 3) return encode_reference(argv[1], argv[2]);
    struct CODEC2 *state = codec2_create(CODEC2_MODE_3200);
    if (!state)
        return 1;
    printf("%d %d %d\n", codec2_samples_per_frame(state), codec2_bits_per_frame(state),
           codec2_bytes_per_frame(state));
    codec2_destroy(state);
    const int unsupported[] = {CODEC2_MODE_2400, CODEC2_MODE_1600, CODEC2_MODE_1400,
        CODEC2_MODE_1300, CODEC2_MODE_1200, CODEC2_MODE_700C, -1};
    for (unsigned i = 0; i < sizeof(unsupported) / sizeof(unsupported[0]); i++)
    {
        state = codec2_create(unsupported[i]);
        if (state)
        {
            codec2_destroy(state);
            return 2;
        }
    }
    return 0;
}
