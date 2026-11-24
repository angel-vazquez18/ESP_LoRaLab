#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "radio/node_radio.h"

#include "radio_bus_fixture.h"
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
        if (!strcmp(argv[1], "settings")) {
            node_radio_settings config = {915000000, 125000, 7, 5, 2, 8};
            assert(node_radio_configure(&radio, &config));
            assert(radio.configured && !radio.ldro_enabled);
            assert(f.modulation[0] == 7 && f.modulation[1] == 4 && f.modulation[2] == 1);
            assert(f.registers[0x740] == 0x14 && f.registers[0x741] == 0x24);
            for (int sf = 7; sf <= 12; sf++) {
                for (unsigned bw = 125000; bw <= 500000; bw *= 2) {
                    config.spreading_factor = sf; config.bandwidth_hz = bw;
                    config.coding_rate_denominator = 8;
                    assert(node_radio_configure(&radio, &config));
                    assert(radio.applied.spreading_factor == sf);
                    assert(radio.applied.bandwidth_hz == bw && f.modulation[2] == 4);
                }
            }
            config.spreading_factor=11; config.bandwidth_hz=125000;
            assert(node_radio_configure(&radio,&config) && f.modulation[3] == 1);
            config.spreading_factor=12; config.bandwidth_hz=250000;
            assert(node_radio_configure(&radio,&config) && f.modulation[3] == 1);
            config.bandwidth_hz=500000; config.frequency_hz=928000000; config.tx_power_dbm=20; config.preamble_symbols=32;
            assert(node_radio_configure(&radio,&config) && f.modulation[3] == 0);
            config.frequency_hz=902000000; config.tx_power_dbm=2; config.preamble_symbols=8;
            assert(node_radio_configure(&radio,&config));
            config = radio.applied; unsigned previous = f.transfers;
            config.frequency_hz = 2400000000U;
            assert(!node_radio_configure(&radio, &config));
            assert(f.transfers == previous && radio.available && radio.configured);
            config = radio.applied; config.coding_rate_denominator = 1;
            assert(!node_radio_configure(&radio, &config));
            config = radio.applied; config.tx_power_dbm = 21;
            assert(!node_radio_configure(&radio, &config));
            assert(f.transfers == previous);
            config = radio.applied; f.fail = true;
            assert(!node_radio_configure(&radio, &config));
            assert(!radio.available && !radio.configured);
            f.fail = false;
            assert(node_radio_init(&radio, &bus, variant));
        }
        if (!strcmp(argv[1], "stop")) {
            assert(node_radio_stop(&radio));
            assert(node_radio_stop(&radio));
            assert(!f.pins[RADIO_FEM_ENABLE]);
        }
        assert(node_radio_init(&radio, &bus, RADIO_HELTEC_V42_GC1109));
    }
    puts("radio boundary passed");
}
