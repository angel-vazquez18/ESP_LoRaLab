#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "radio/node_radio.h"

typedef struct {
    int64_t time;
    bool pins[6], busy, absent, fail, gpio_fail, reject;
    unsigned transfers;
    uint8_t opcodes[128];
} fixture;
static int64_t now(void *p) { return ((fixture *)p)->time; }
static void delay(void *p, uint32_t us) { ((fixture *)p)->time += us; }
static bool set(void *p, node_radio_signal pin, bool value) { ((fixture *)p)->pins[pin] = value; return !((fixture *)p)->gpio_fail; }
static int get(void *p, node_radio_signal pin) { return pin == RADIO_BUSY ? ((fixture *)p)->busy : 0; }
static bool transfer(void *p, const uint8_t *tx, uint8_t *rx, size_t count) {
    fixture *f = p;
    assert(f->transfers < 128);
    f->opcodes[f->transfers++] = tx[0];
    memset(rx, 0, count);
    if (tx[0] == 0xc0) rx[count - 1] = f->absent ? 0xff : (f->reject ? 0x28 : 0x24);
    return !f->fail;
}
int main(int argc, char **argv) {
    assert(argc == 2);
    fixture f = {0};
    node_radio radio = {0};
    node_radio_bus bus = {&f, now, delay, set, get, transfer};
    node_radio_variant variant = RADIO_HELTEC_V43_KCT8103L;
    if (!strcmp(argv[1], "busy")) f.busy = true;
    if (!strcmp(argv[1], "absent")) f.absent = true;
    if (!strcmp(argv[1], "command_rejected")) f.reject = true;
    if (!strcmp(argv[1], "io_failure")) f.fail = true;
    if (!strcmp(argv[1], "gpio_failure")) f.gpio_fail = true;
    if (!strcmp(argv[1], "unknown_board")) variant = RADIO_BOARD_UNKNOWN;
    bool success = node_radio_init(&radio, &bus, variant);
    if (f.busy || f.absent || f.fail || f.gpio_fail || f.reject || variant == RADIO_BOARD_UNKNOWN) {
        assert(!success && !radio.available);
        assert(!f.pins[RADIO_FEM_ENABLE] && !f.pins[RADIO_FEM_POWER]);
        assert(f.time <= 250000);
    } else {
        assert(success && radio.available);
        assert(f.opcodes[0] == 0x80); // Start in standby, never TX/RX.
        assert(memchr(f.opcodes, 0x97, f.transfers)); // TCXO control.
        assert(memchr(f.opcodes, 0x9d, f.transfers)); // DIO2 RF switch.
        assert(memchr(f.opcodes, 0x8a, f.transfers)); // LoRa packet type.
        assert(!memchr(f.opcodes, 0x83, f.transfers));
        if (!strcmp(argv[1], "stop")) {
            assert(node_radio_stop(&radio));
            assert(node_radio_stop(&radio));
            assert(!f.pins[RADIO_FEM_ENABLE]);
        }
        assert(node_radio_init(&radio, &bus, RADIO_HELTEC_V42_GC1109));
    }
    puts("radio boundary passed");
}
