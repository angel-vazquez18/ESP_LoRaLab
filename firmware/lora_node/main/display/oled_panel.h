#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define OLED_FRAME_BYTES 1024U
#define OLED_IO_TIMEOUT_MS 5U

typedef struct {
    void *context;
    bool (*write)(void *, const uint8_t *, size_t, unsigned timeout_ms);
} oled_panel_port;

bool oled_panel_initialize(oled_panel_port port);
bool oled_panel_frame(oled_panel_port port, const uint8_t frame[OLED_FRAME_BYTES]);
