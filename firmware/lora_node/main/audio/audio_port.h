#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t samples, dma_frames, underflows;
    bool done, failed;
    uint32_t raw_left_nonzero, raw_right_nonzero, raw_left_or, raw_right_or;
} node_audio_progress;

// stop must quiesce DMA before its borrowed buffer can be released.
typedef struct {
    bool playback, capture;
    bool (*start)(void *context, uint8_t *pcm, uint32_t samples, bool capture);
    void (*poll)(void *context, node_audio_progress *progress);
    void (*stop)(void *context);
} node_audio_port;
