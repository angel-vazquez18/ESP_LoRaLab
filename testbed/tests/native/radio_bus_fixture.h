#pragma once
#include "radio/node_radio.h"
#include <assert.h>
#include <string.h>
typedef struct {
    int64_t time;
    bool pins[6], busy, absent, fail, gpio_fail, reject;
    unsigned transfers;
    uint8_t opcodes[2048], registers[65536], modulation[4];
} fixture;
static int64_t now(void *p) { return ((fixture *)p)->time; }
static void delay(void *p, uint32_t us) { ((fixture *)p)->time += us; }
static bool set(void *p, node_radio_signal pin, bool value) { ((fixture *)p)->pins[pin] = value; return !((fixture *)p)->gpio_fail; }
static int get(void *p, node_radio_signal pin) { return pin == RADIO_BUSY ? ((fixture *)p)->busy : 0; }
static bool transfer(void *p, const uint8_t *tx, uint8_t *rx, size_t count) {
    fixture *f = p;
    assert(f->transfers < 2048);
    f->opcodes[f->transfers++] = tx[0];
    memset(rx, 0, count);
    if (tx[0] == 0x0d) memcpy(f->registers + ((tx[1] << 8) | tx[2]), tx + 3, count - 3);
    if (tx[0] == 0x1d) memcpy(rx + 4, f->registers + ((tx[1] << 8) | tx[2]), count - 4);
    if (tx[0] == 0x8b) memcpy(f->modulation, tx + 1, 4);
    if (tx[0] == 0x11) rx[count - 1] = 1;
    if (tx[0] == 0xc0) rx[count - 1] = f->absent ? 0xff : (f->reject ? 0x28 : 0x24);
    return !f->fail;
}
