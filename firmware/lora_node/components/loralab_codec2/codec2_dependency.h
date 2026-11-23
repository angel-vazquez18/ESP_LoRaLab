#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t samples, bits, bytes, sample_rate_hz;
} codec2_frame_format;

// Query the actual library; zero the result when the selected mode is unavailable.
bool codec2_dependency_query(unsigned mode, codec2_frame_format *format);
const char *codec2_dependency_version(void);
const char *codec2_dependency_revision(void);
