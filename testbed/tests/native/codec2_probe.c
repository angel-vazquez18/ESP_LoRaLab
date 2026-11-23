#include <stdio.h>
#include "codec2.h"

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

int main(int argc, char **argv)
{
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
