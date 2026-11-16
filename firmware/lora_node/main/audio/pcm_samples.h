#pragma once
#include <stdint.h>
// Signed little-endian mono to equal stereo slots, truncating toward zero at 1/8.
void pcm_output_stereo(const uint8_t *source, int16_t *target, uint32_t samples);
