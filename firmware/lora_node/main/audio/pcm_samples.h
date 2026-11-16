#pragma once
#include <stdint.h>
int16_t pcm_input_sample(uint32_t slot);
// Signed little-endian mono to equal stereo slots, truncating toward zero at 1/8.
void pcm_output_stereo(const uint8_t *source, int16_t *target, uint32_t samples);
