#include "radio_bus_fixture.h"
static fixture boundary;
static node_radio radio;
void *native_radio_create(void) {
    memset(&boundary, 0, sizeof(boundary));
    node_radio_bus bus = {&boundary, now, delay, set, get, transfer};
    assert(node_radio_init(&radio, &bus, RADIO_HELTEC_V42_GC1109));
    return &radio;
}
void native_radio_fail(void) { boundary.fail = true; }
unsigned native_radio_transfers(void) { return boundary.transfers; }
