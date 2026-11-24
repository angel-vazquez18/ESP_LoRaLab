#include <stdio.h>
#include "codec2.h"

int main(void)
{
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
