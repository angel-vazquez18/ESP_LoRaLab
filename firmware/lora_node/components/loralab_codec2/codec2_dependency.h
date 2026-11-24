#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint32_t samples, bits, bytes, sample_rate_hz;
} codec2_frame_format;

// Query the actual library; zero the result when the selected mode is unavailable.
bool codec2_dependency_query(unsigned mode, codec2_frame_format *format);
const char *codec2_dependency_version(void);
const char *codec2_dependency_revision(void);

// One fresh state per clip; encoded bytes use the upstream packed format.
typedef struct CODEC2 codec2_encoder;
codec2_encoder *codec2_encoder_create(void);
bool codec2_encoder_frame(codec2_encoder *state, short *samples, size_t sample_count,
                          uint8_t *output, size_t capacity);
void codec2_encoder_destroy(codec2_encoder *state);
