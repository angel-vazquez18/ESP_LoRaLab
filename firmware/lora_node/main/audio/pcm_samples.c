#include "pcm_samples.h"
int16_t pcm_input_sample(uint32_t slot)
{
    int32_t value = slot >> 16; // 24-bit MSB-aligned input: discard its low eight data bits.
    if (value & 0x8000) value -= 65536;
    return (int16_t)value;
}

void pcm_output_stereo(const uint8_t *source, int16_t *target, uint32_t samples)
{
    for (uint32_t i = 0; i < samples; i++) {
        int32_t value = source[i * 2] | ((uint32_t)source[i * 2 + 1] << 8);
        if (value & 0x8000) value -= 65536;
        target[i * 2] = target[i * 2 + 1] = (int16_t)(value / 8);
    }
}
