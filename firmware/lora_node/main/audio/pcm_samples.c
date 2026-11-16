#include "pcm_samples.h"
void pcm_output_stereo(const uint8_t *source, int16_t *target, uint32_t samples)
{
    for (uint32_t i = 0; i < samples; i++) {
        int32_t value = source[i * 2] | ((uint32_t)source[i * 2 + 1] << 8);
        if (value & 0x8000) value -= 65536;
        target[i * 2] = target[i * 2 + 1] = (int16_t)(value / 8);
    }
}
