#pragma once
struct FakeI2sHw { int port; };
extern FakeI2sHw fakeI2sHardware[2];
#define I2S_LL_GET_HW(port) (&fakeI2sHardware[port])
void i2s_ll_tx_reset(FakeI2sHw*);
#if defined(CONFIG_IDF_TARGET_ESP32S3)
void i2s_ll_tx_set_ws_idle_pol(FakeI2sHw*, bool);
void i2s_ll_tx_update(FakeI2sHw*);
#else
void i2s_ll_tx_enable_right_first(FakeI2sHw*, bool);
void i2s_ll_tx_stop_on_fifo_empty(FakeI2sHw*, bool);
#endif
