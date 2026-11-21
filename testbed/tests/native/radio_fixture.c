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
        if (!strncmp(argv[1], "tx", 2)) {
            node_radio_settings config = {915000000,125000,7,5,2,8};
            assert(node_radio_configure(&radio,&config));
            uint8_t bytes[]={0x01,0x80,0xff};
            node_radio_reference reference={1,7,3,0,2};
            unsigned before=f.transfers;
            assert(!node_radio_tx(&radio,bytes,0,&reference,100000));
            assert(!node_radio_tx(&radio,bytes,256,&reference,100000));
            assert(!node_radio_tx(&radio,bytes,sizeof(bytes),&reference,0));
            assert(f.transfers==before);
            assert(node_radio_tx(&radio,bytes,sizeof(bytes),&reference,100000));
            assert(f.tx_length==3 && !memcmp(bytes,f.tx_bytes,3));
            assert(!node_radio_tx(&radio,bytes,3,&reference,100000));
            node_radio_event event;
            assert(!node_radio_poll(&radio,&event));
            if (!strcmp(argv[1],"tx_cancel")) assert(node_radio_stop(&radio));
            else if (!strcmp(argv[1],"tx_timeout")) f.time += 100000;
            else if (!strcmp(argv[1],"tx_irq_timeout")) f.irq=0x0200;
            else if (!strcmp(argv[1],"tx_bad_irq")) f.irq=2;
            else if (!strcmp(argv[1],"tx_io_failure")) { f.fail=true; f.irq=1; }
            else { f.time+=50000; f.irq=1; }
            assert(!node_radio_poll(&radio,NULL)); // Backpressure retains the terminal event.
            assert(!node_radio_tx(&radio,bytes,3,&reference,100000));
            assert(node_radio_poll(&radio,&event));
            assert(event.reference.frame_seq==7 && event.reference.attempt_index==2);
            assert(event.frame_bytes==3 && event.command_us >= 0);
            assert(event.status==(!strcmp(argv[1],"tx") ? RADIO_DONE :
                !strcmp(argv[1],"tx_cancel") ? RADIO_CANCELLED :
                (!strcmp(argv[1],"tx_timeout") || !strcmp(argv[1],"tx_irq_timeout")) ? RADIO_TIMEOUT : RADIO_FAILED));
            assert((event.done_us >= event.command_us) == (event.status==RADIO_DONE));
            assert(!node_radio_poll(&radio,&event));
            assert(!f.pins[RADIO_FEM_ENABLE] && !f.pins[RADIO_FEM_MODE]);
            if (!f.fail) {
                assert(node_radio_tx(&radio,bytes,3,&reference,100000));
                f.irq=1; assert(node_radio_poll(&radio,&event) && event.status==RADIO_DONE);
            }
            f.fail=false;
        }
        if (!strncmp(argv[1],"rx",2)) {
            node_radio_settings config={915000000,125000,7,5,2,8};
            assert(node_radio_configure(&radio,&config));
            unsigned before=f.transfers;
            assert(!node_radio_rx(&radio,0,100000));
            assert(!node_radio_rx(&radio,256,100000));
            assert(!node_radio_rx(&radio,255,0));
            assert(f.transfers==before);
            assert(node_radio_rx(&radio,3,100000));
            assert(!f.pins[RADIO_FEM_MODE] && f.pins[RADIO_FEM_ENABLE]);
            node_radio_event event;
            assert(!node_radio_poll(&radio,&event));
            if (!strcmp(argv[1],"rx_timeout")) f.time+=100000;
            else if (!strcmp(argv[1],"rx_irq_timeout")) f.irq=0x0200;
            else if (!strcmp(argv[1],"rx_cancel")) assert(node_radio_stop(&radio));
            else {
                f.rx_length=!strcmp(argv[1],"rx_oversize")?4:!strcmp(argv[1],"rx_empty")?0:3;
                if (!strcmp(argv[1],"rx_fifo_failure")) f.fail_opcode=0x1e;
                memcpy(f.rx_bytes,(uint8_t[]){1,128,255,7},4);
                f.irq=!strcmp(argv[1],"rx_crc")?0x42:!strcmp(argv[1],"rx_header")?0x20:2;
            }
            assert(!node_radio_poll(&radio,NULL));
            assert(!node_radio_rx(&radio,3,100000));
            assert(node_radio_poll(&radio,&event) && event.kind==RADIO_EVENT_RX);
            if (!strcmp(argv[1],"rx")) {
                assert(event.status==RADIO_DONE && event.crc_ok && event.signal_valid);
                assert(event.frame_bytes==3 && !memcmp(event.bytes,f.rx_bytes,3));
                assert(event.rssi_dbm==-86.5f && event.snr_db==-1.25f);
            } else {
                assert(event.status!=RADIO_DONE);
                if (!strcmp(argv[1],"rx_crc")) assert(!event.crc_ok && event.signal_valid);
                if (!strcmp(argv[1],"rx_timeout")) assert(!event.signal_valid && event.done_us==-1);
                if (!strcmp(argv[1],"rx_oversize")) assert(event.status==RADIO_OVERSIZE);
            }
            assert(!node_radio_poll(&radio,&event));
            assert(!f.pins[RADIO_FEM_ENABLE]);
            f.fail_opcode=0;
            if (!radio.available) {
                assert(!strcmp(argv[1],"rx_fifo_failure"));
                assert(node_radio_init(&radio,&bus,variant));
                assert(node_radio_configure(&radio,&config));
            }
            assert(node_radio_rx(&radio,255,100000));
            f.rx_length=3; f.irq=2;
            assert(node_radio_poll(&radio,&event) && event.status==RADIO_DONE);
        }
        assert(node_radio_init(&radio, &bus, RADIO_HELTEC_V42_GC1109));
    }
    puts("radio boundary passed");
}
