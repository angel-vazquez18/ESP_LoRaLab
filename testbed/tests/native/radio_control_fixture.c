#include "radio_bus_fixture.h"
static fixture boundaries[4];
static node_radio radios[4];
static unsigned current=3;
static fixture *boundary_for(void *radio) {
    for (unsigned i=0;i<4;i++) if (radio==&radios[i]) return &boundaries[i];
    assert(false); return NULL;
}
void *native_radio_create(void) {
    current=(current+1)%4;
    fixture *f=&boundaries[current]; memset(f,0,sizeof(*f));
    node_radio_bus bus={f,now,delay,set,get,transfer};
    assert(node_radio_init(&radios[current],&bus,RADIO_HELTEC_V42_GC1109));
    return &radios[current];
}
void native_radio_fail(void) { boundaries[current].fail=true; }
unsigned native_radio_transfers(void) { return boundaries[current].transfers; }
void native_radio_time(void *radio, int64_t time) { boundary_for(radio)->time=time; }
void native_radio_inject(void *radio, const void *bytes, unsigned length, unsigned irq) {
    assert(length<=255); fixture *f=boundary_for(radio);
    memcpy(f->rx_bytes,bytes,length); f->rx_length=length; f->irq=irq;
}
unsigned native_radio_sent(void *radio, void *out) {
    fixture *f=boundary_for(radio); memcpy(out,f->tx_bytes,f->tx_length); return f->tx_length;
}
void native_radio_tx_done(void *radio) { boundary_for(radio)->irq=1; }

bool native_radio_configure_default(void *radio) {
    node_radio_settings settings={915000000,125000,7,5,2,8};
    return node_radio_configure(radio,&settings);
}

unsigned native_radio_generation(void *radio) {return boundary_for(radio)->tx_generation;}
bool native_radio_listening(void *radio) {return ((node_radio *)radio)->operation==2;}

bool native_radio_transmitting(void *radio) {return ((node_radio *)radio)->operation==1;}
