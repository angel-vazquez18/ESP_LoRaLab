#include "oled_panel.h"
#include <string.h>

static bool write(oled_panel_port port, const uint8_t *data, size_t length)
{
    return port.write && port.write(port.context, data, length, OLED_IO_TIMEOUT_MS);
}

bool oled_panel_initialize(oled_panel_port port)
{
    // SSD1315-compatible 128x64 setup; keep the panel off until RAM is written.
    const uint8_t commands[] = {
        0x00, 0xae, 0xd5, 0x80, 0xa8, 0x3f, 0xd3, 0x00, 0x40,
        0x8d, 0x14, 0x20, 0x00, 0xa1, 0xc8, 0xda, 0x12,
        0x81, 0x7f, 0xd9, 0xf1, 0xdb, 0x40, 0xa4, 0xa6, 0x2e,
    };
    return write(port, commands, sizeof(commands));
}

bool oled_panel_frame(oled_panel_port port, const uint8_t frame[OLED_FRAME_BYTES])
{
    if (!frame) return false;
    const uint8_t address[] = {0x00, 0x21, 0x00, 0x7f, 0x22, 0x00, 0x07};
    if (!write(port, address, sizeof(address))) return false;
    uint8_t packet[129] = {0x40};
    for (unsigned page = 0; page < 8; page++) {
        memcpy(packet + 1, frame + page * 128, 128);
        if (!write(port, packet, sizeof(packet))) return false;
    }
    const uint8_t display_on[] = {0x00, 0xaf};
    return write(port, display_on, sizeof(display_on));
}
