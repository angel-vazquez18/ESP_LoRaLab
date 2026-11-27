#include "radio/node_radio.h"
#include "sx126x.h"
#include "sx126x_hal.h"
#include "sx126x_regs.h"
#include <string.h>

#define BUSY_TIMEOUT_US 100000LL
#define SPI_BYTES 260U

static bool ready(node_radio *r)
{
    int64_t deadline = r->bus.now_us(r->bus.context) + BUSY_TIMEOUT_US;
    // The iteration bound also protects against a broken time source.
    for (unsigned i = 0; i < 101; i++) {
        int busy = r->bus.get(r->bus.context, RADIO_BUSY);
        if (busy == 0) return true;
        if (busy < 0 || r->bus.now_us(r->bus.context) >= deadline) break;
        r->bus.delay_us(r->bus.context, 1000);
    }
    r->error = "radio_busy_timeout";
    r->available = false;
    return false;
}
static sx126x_hal_status_t exchange(const void *context, const uint8_t *cmd, uint16_t cmd_len,
                                  const uint8_t *data, uint8_t *out, uint16_t length)
{
    node_radio *r = (node_radio *)context;
    uint8_t tx[SPI_BYTES] = {0}, rx[SPI_BYTES] = {0};
    if (!cmd || !cmd_len || (size_t)cmd_len + length > SPI_BYTES || !ready(r))
        return SX126X_HAL_STATUS_ERROR;
    memcpy(tx, cmd, cmd_len);
    if (data && length) memcpy(tx + cmd_len, data, length);
    if (!r->bus.transfer(r->bus.context, tx, rx, cmd_len + length)) {
        r->error = "radio_spi_error";
        r->available = false;
        return SX126X_HAL_STATUS_ERROR;
    }
    if (out && length) memcpy(out, rx + cmd_len, length);
    return ready(r) ? SX126X_HAL_STATUS_OK : SX126X_HAL_STATUS_ERROR;
}
sx126x_hal_status_t sx126x_hal_write(const void *context, const uint8_t *cmd, uint16_t cmd_len,
                                  const uint8_t *data, uint16_t length)
{ return exchange(context, cmd, cmd_len, data, NULL, length); }
sx126x_hal_status_t sx126x_hal_read(const void *context, const uint8_t *cmd, uint16_t cmd_len,
                                 uint8_t *data, uint16_t length)
{ return exchange(context, cmd, cmd_len, NULL, data, length); }
sx126x_hal_status_t sx126x_hal_reset(const void *context)
{
    node_radio *r = (node_radio *)context;
    if (!r->bus.set(r->bus.context, RADIO_RESET, false)) return SX126X_HAL_STATUS_ERROR;
    r->bus.delay_us(r->bus.context, 200);
    if (!r->bus.set(r->bus.context, RADIO_RESET, true)) return SX126X_HAL_STATUS_ERROR;
    r->bus.delay_us(r->bus.context, 10000);
    return ready(r) ? SX126X_HAL_STATUS_OK : SX126X_HAL_STATUS_ERROR;
}
sx126x_hal_status_t sx126x_hal_wakeup(const void *context)
{
    // The finite driver stays in standby; wake via a status transaction if needed.
    const uint8_t cmd = 0xc0;
    uint8_t status;
    return exchange(context, &cmd, 1, NULL, &status, 1);
}
static bool status_ok(node_radio *r)
{
    sx126x_chip_status_t status;
    if (sx126x_get_status(r, &status) != SX126X_STATUS_OK) return false;
    r->status_observed = true;
    r->last_chip_mode = status.chip_mode;
    r->last_command_status = status.cmd_status;
    // SX1262 on the V4.3 bench reports RFU (1) after valid standby writes.
    return status.chip_mode == SX126X_CHIP_MODE_STBY_RC &&
        (status.cmd_status == SX126X_CMD_STATUS_RFU ||
         status.cmd_status == SX126X_CMD_STATUS_DATA_AVAILABLE ||
         status.cmd_status == SX126X_CMD_STATUS_CMD_TX_DONE);
}
static void disable(node_radio *r)
{
    r->available = r->configured = false;
    r->bus.set(r->bus.context, RADIO_FEM_ENABLE, false);
    r->bus.set(r->bus.context, RADIO_FEM_MODE, false);
    r->bus.set(r->bus.context, RADIO_FEM_POWER, false);
    r->bus.set(r->bus.context, RADIO_RESET, false);
}
bool node_radio_stop(node_radio *r)
{
    if (!r || !r->bus.set) return false;
    if (r->operation) {
        r->operation = 0;
        r->event.status = RADIO_CANCELLED;
        r->event_pending = true;
    }
    bool pins = r->bus.set(r->bus.context, RADIO_FEM_ENABLE, false);
    pins = r->bus.set(r->bus.context, RADIO_FEM_MODE, false) && pins;
    bool ok = r->available && pins &&
        sx126x_set_standby(r, SX126X_STANDBY_CFG_RC) == SX126X_STATUS_OK &&
        sx126x_clear_irq_status(r, SX126X_IRQ_ALL) == SX126X_STATUS_OK && status_ok(r);
    if (!ok) { disable(r); if (r->event_pending) r->event.status = RADIO_FAILED; if (!r->error) r->error = "radio_stop_failed"; }
    return ok;
}
const char *node_radio_variant_name(node_radio_variant v)
{
    return v == RADIO_HELTEC_V42_GC1109 ? "heltec_v4_2_gc1109" :
        v == RADIO_HELTEC_V43_KCT8103L ? "heltec_v4_3_kct8103l" : "unselected";
}
bool node_radio_init(node_radio *r, const node_radio_bus *bus, node_radio_variant variant)
{
    if (!r || !bus || !bus->now_us || !bus->delay_us || !bus->set || !bus->get || !bus->transfer)
        return false;
    *r = (node_radio){.bus = *bus, .variant = variant, .error = NULL};
    if (variant != RADIO_HELTEC_V42_GC1109 && variant != RADIO_HELTEC_V43_KCT8103L) {
        r->error = "radio_board_unselected";
        return false;
    }
    disable(r);
    #define INITIALIZE(step, call) \
        (r->initialization_step = (step), r->status_observed = false, \
         (call) == SX126X_STATUS_OK && status_ok(r))
    r->initialization_step = "power_and_reset";
    bool ok = bus->set(bus->context, RADIO_FEM_POWER, true) &&
        sx126x_reset(r) == SX126X_STATUS_OK &&
        INITIALIZE("standby", sx126x_set_standby(r, SX126X_STANDBY_CFG_RC)) &&
        INITIALIZE("tcxo", sx126x_set_dio3_as_tcxo_ctrl(r, SX126X_TCXO_CTRL_1_8V, 320)) &&
        INITIALIZE("clear_errors", sx126x_clear_device_errors(r)) &&
        INITIALIZE("calibrate", sx126x_cal(r, SX126X_CAL_ALL)) &&
        INITIALIZE("regulator", sx126x_set_reg_mode(r, SX126X_REG_MODE_DCDC)) &&
        INITIALIZE("rf_switch", sx126x_set_dio2_as_rf_sw_ctrl(r, true)) &&
        INITIALIZE("packet_type", sx126x_set_pkt_type(r, SX126X_PKT_TYPE_LORA)) &&
        INITIALIZE("buffer_base", sx126x_set_buffer_base_address(r, 0, 0)) &&
        INITIALIZE("irq_setup", sx126x_set_dio_irq_params(r, 0, 0, 0, 0)) &&
        INITIALIZE("clear_irq", sx126x_clear_irq_status(r, SX126X_IRQ_ALL));
    #undef INITIALIZE
    if (!ok) {
        if (!r->error) r->error = "radio_initialization_failed";
        // Attempt standby, then physically disable the front end even on a stuck bus.
        if (!bus->get(bus->context, RADIO_BUSY)) sx126x_set_standby(r, SX126X_STANDBY_CFG_RC);
        disable(r);
    } else {
        r->initialization_step = NULL;
    }
    r->available = ok;
    return ok;
}

bool node_radio_valid_settings(const node_radio_settings *s)
{
    return s && s->frequency_hz >= 902000000 && s->frequency_hz <= 928000000 &&
        s->frequency_hz % 1000 == 0 &&
        (s->bandwidth_hz == 125000 || s->bandwidth_hz == 250000 || s->bandwidth_hz == 500000) &&
        s->spreading_factor >= 7 && s->spreading_factor <= 12 &&
        s->coding_rate_denominator >= 5 && s->coding_rate_denominator <= 8 &&
        s->tx_power_dbm >= 2 && s->tx_power_dbm <= 20 &&
        s->preamble_symbols >= 8 && s->preamble_symbols <= 32;
}
bool node_radio_configure(node_radio *r, const node_radio_settings *s)
{
    if (!r || !r->available || r->operation || r->event_pending || !node_radio_valid_settings(s)) return false;
    bool ldro = (1U << s->spreading_factor) * 1000U >= 16U * s->bandwidth_hz;
    sx126x_mod_params_lora_t modulation = {
        .sf = (sx126x_lora_sf_t)s->spreading_factor,
        .bw = s->bandwidth_hz == 125000 ? SX126X_LORA_BW_125 :
              s->bandwidth_hz == 250000 ? SX126X_LORA_BW_250 : SX126X_LORA_BW_500,
        .cr = (sx126x_lora_cr_t)(s->coding_rate_denominator - 4), .ldro = ldro};
    sx126x_pkt_params_lora_t packet = {.preamble_len_in_symb = s->preamble_symbols,
        .header_type = SX126X_LORA_PKT_EXPLICIT, .pld_len_in_bytes = 255,
        .crc_is_on = true, .invert_iq_is_on = false};
    sx126x_pa_cfg_params_t pa = {.pa_duty_cycle = 4, .hp_max = 7, .device_sel = 0, .pa_lut = 1};
    uint8_t sync[] = {0x14, 0x24}, readback[2] = {0};
    sx126x_pkt_type_t type;
    #define APPLY(call) ((call) == SX126X_STATUS_OK && status_ok(r))
    bool ok = node_radio_stop(r) &&
        APPLY(sx126x_cal_img(r, 0xe1, 0xe9)) &&
        APPLY(sx126x_set_rf_freq(r, s->frequency_hz)) &&
        APPLY(sx126x_set_pa_cfg(r, &pa)) &&
        APPLY(sx126x_cfg_tx_clamp(r)) &&
        APPLY(sx126x_set_tx_params(r, s->tx_power_dbm, SX126X_RAMP_200_US)) &&
        APPLY(sx126x_set_lora_mod_params(r, &modulation)) &&
        APPLY(sx126x_set_lora_pkt_params(r, &packet)) &&
        APPLY(sx126x_write_register(r, SX126X_REG_LR_SYNCWORD, sync, 2)) &&
        sx126x_read_register(r, SX126X_REG_LR_SYNCWORD, readback, 2) == SX126X_STATUS_OK &&
        !memcmp(sync, readback, 2) && sx126x_get_pkt_type(r, &type) == SX126X_STATUS_OK &&
        type == SX126X_PKT_TYPE_LORA;
    #undef APPLY
    if (!ok) {
        node_radio_stop(r);
        disable(r);
        r->error = "radio_configuration_failed";
        return false;
    }
    r->applied = *s;
    r->ldro_enabled = ldro;
    r->configured = true;
    r->error = NULL;
    return true;
}

static void receive_done(node_radio *r, sx126x_irq_mask_t irq, int64_t observed);
static void complete(node_radio *r, node_radio_outcome status, int64_t observed)
{
    r->operation = 0;
    r->event.status = status;
    r->event.done_us = observed;
    if (!node_radio_stop(r)) r->event.status = RADIO_FAILED;
    r->event_pending = true;
}
bool node_radio_tx(node_radio *r, const uint8_t *bytes, size_t length,
                   const node_radio_reference *reference, uint32_t timeout_us)
{
    if (!r || !r->available || !r->configured || r->operation || r->event_pending ||
        !bytes || !length || length > 255 || !reference || !reference->session_id ||
        !reference->frame_seq || !reference->message_id || reference->fragment_index > 4095 ||
        reference->attempt_index < 1 || reference->attempt_index > 6 ||
        !timeout_us || timeout_us > 30000000) return false;
    if (!node_radio_stop(r)) return false;
    r->event = (node_radio_event){.reference=*reference, .frame_bytes=length,
        .command_us=-1, .done_us=-1, .status=RADIO_FAILED};
    r->operation = 1;
    sx126x_pkt_params_lora_t packet = {.preamble_len_in_symb=r->applied.preamble_symbols,
        .header_type=SX126X_LORA_PKT_EXPLICIT, .pld_len_in_bytes=length,
        .crc_is_on=true, .invert_iq_is_on=false};
    bool ok = sx126x_set_lora_pkt_params(r,&packet) == SX126X_STATUS_OK &&
        sx126x_write_buffer(r,0,bytes,length) == SX126X_STATUS_OK &&
        sx126x_clear_irq_status(r,SX126X_IRQ_ALL) == SX126X_STATUS_OK &&
        sx126x_set_dio_irq_params(r,SX126X_IRQ_TX_DONE|SX126X_IRQ_TIMEOUT,
            SX126X_IRQ_TX_DONE|SX126X_IRQ_TIMEOUT,0,0) == SX126X_STATUS_OK &&
        sx126x_set_rx_tx_fallback_mode(r,SX126X_FALLBACK_STDBY_RC) == SX126X_STATUS_OK &&
        r->bus.set(r->bus.context,RADIO_FEM_MODE,true) &&
        r->bus.set(r->bus.context,RADIO_FEM_ENABLE,true);
    if (ok) {
        r->event.command_us=r->bus.now_us(r->bus.context);
        r->deadline_us=r->event.command_us+timeout_us;
        uint32_t ticks=((uint64_t)timeout_us*64+999)/1000;
        ok=sx126x_set_tx_with_timeout_in_rtc_step(r,ticks)==SX126X_STATUS_OK;
        sx126x_chip_status_t status;
        ok=ok && sx126x_get_status(r,&status)==SX126X_STATUS_OK &&
            (status.chip_mode==SX126X_CHIP_MODE_TX || status.chip_mode==SX126X_CHIP_MODE_STBY_RC) &&
            status.cmd_status!=SX126X_CMD_STATUS_CMD_TIMEOUT &&
            status.cmd_status!=SX126X_CMD_STATUS_CMD_PROCESS_ERROR &&
            status.cmd_status!=SX126X_CMD_STATUS_CMD_EXEC_FAILURE;
    }
    if (!ok) complete(r,RADIO_FAILED,-1);
    return true;
}
bool node_radio_poll(node_radio *r, node_radio_event *out)
{
    if (!r) return false;
    if (r->operation) {
        int64_t observed=r->bus.now_us(r->bus.context);
        int dio=r->bus.get(r->bus.context,RADIO_DIO1);
        if (observed>=r->deadline_us) complete(r,RADIO_TIMEOUT,-1);
        else if (dio<0) complete(r,RADIO_FAILED,-1);
        else if (dio) {
            sx126x_irq_mask_t irq=0;
            if (sx126x_get_irq_status(r,&irq)!=SX126X_STATUS_OK) complete(r,RADIO_FAILED,-1);
            else if (irq & SX126X_IRQ_TIMEOUT) complete(r,RADIO_TIMEOUT,-1);
            else if (r->operation == 2) receive_done(r,irq,observed);
            else if (irq == SX126X_IRQ_TX_DONE) complete(r,RADIO_DONE,observed);
            else complete(r,RADIO_FAILED,-1);
        }
    }
    if (!r->event_pending || !out) return false;
    *out=r->event;
    r->event_pending=false;
    return true;
}

bool node_radio_rx(node_radio *r, size_t maximum, uint32_t timeout_us)
{
    if (!r || !r->available || !r->configured || r->operation || r->event_pending ||
        !maximum || maximum>255 || !timeout_us || timeout_us>30000000) return false;
    if (!node_radio_stop(r)) return false;
    r->event=(node_radio_event){.kind=RADIO_EVENT_RX,.command_us=-1,.done_us=-1,.status=RADIO_FAILED};
    r->operation=2;
    r->rx_maximum=maximum;
    sx126x_pkt_params_lora_t packet={.preamble_len_in_symb=r->applied.preamble_symbols,
        .header_type=SX126X_LORA_PKT_EXPLICIT,.pld_len_in_bytes=255,.crc_is_on=true,.invert_iq_is_on=false};
    sx126x_irq_mask_t mask=SX126X_IRQ_RX_DONE|SX126X_IRQ_TIMEOUT|SX126X_IRQ_CRC_ERROR|SX126X_IRQ_HEADER_ERROR;
    bool ok=sx126x_set_lora_pkt_params(r,&packet)==SX126X_STATUS_OK &&
        sx126x_clear_irq_status(r,SX126X_IRQ_ALL)==SX126X_STATUS_OK &&
        sx126x_set_dio_irq_params(r,mask,mask,0,0)==SX126X_STATUS_OK &&
        sx126x_set_rx_tx_fallback_mode(r,SX126X_FALLBACK_STDBY_RC)==SX126X_STATUS_OK &&
        r->bus.set(r->bus.context,RADIO_FEM_MODE,false) &&
        r->bus.set(r->bus.context,RADIO_FEM_ENABLE,true);
    if (ok) {
        r->event.command_us=r->bus.now_us(r->bus.context);
        r->deadline_us=r->event.command_us+timeout_us;
        uint32_t ticks=((uint64_t)timeout_us*64+999)/1000;
        ok=sx126x_set_rx_with_timeout_in_rtc_step(r,ticks)==SX126X_STATUS_OK;
        sx126x_chip_status_t status;
        ok=ok && sx126x_get_status(r,&status)==SX126X_STATUS_OK &&
            (status.chip_mode==SX126X_CHIP_MODE_RX || status.chip_mode==SX126X_CHIP_MODE_STBY_RC) &&
            status.cmd_status!=SX126X_CMD_STATUS_CMD_TIMEOUT &&
            status.cmd_status!=SX126X_CMD_STATUS_CMD_PROCESS_ERROR &&
            status.cmd_status!=SX126X_CMD_STATUS_CMD_EXEC_FAILURE;
    }
    if (!ok) complete(r,RADIO_FAILED,-1);
    return true;
}
static void receive_done(node_radio *r, sx126x_irq_mask_t irq, int64_t observed)
{
    if (!(irq & SX126X_IRQ_RX_DONE)) {
        complete(r,irq & SX126X_IRQ_HEADER_ERROR ? RADIO_HEADER_ERROR :
            irq & SX126X_IRQ_CRC_ERROR ? RADIO_CRC_ERROR : RADIO_FAILED,-1);
        return;
    }
    sx126x_rx_buffer_status_t buffer;
    // Preserve chip half-dB RSSI and quarter-dB signed SNR; vendor helper rounds them.
    const uint8_t status_cmd[]={0x14,0x00};
    uint8_t signal[3];
    bool ok=sx126x_get_rx_buffer_status(r,&buffer)==SX126X_STATUS_OK &&
        sx126x_hal_read(r,status_cmd,2,signal,3)==SX126X_HAL_STATUS_OK;
    if (!ok) { complete(r,RADIO_FAILED,observed); return; }
    r->event.frame_bytes=buffer.pld_len_in_bytes;
    r->event.signal_valid=true;
    r->event.rssi_dbm=-(float)signal[0]/2.0f;
    r->event.snr_db=(float)(int8_t)signal[1]/4.0f;
    r->event.crc_ok=!(irq & (SX126X_IRQ_CRC_ERROR|SX126X_IRQ_HEADER_ERROR));
    node_radio_outcome outcome=RADIO_DONE;
    if (irq & SX126X_IRQ_HEADER_ERROR) outcome=RADIO_HEADER_ERROR;
    else if (!r->event.crc_ok) outcome=RADIO_CRC_ERROR;
    else if (!buffer.pld_len_in_bytes || buffer.pld_len_in_bytes>r->rx_maximum) outcome=RADIO_OVERSIZE;
    else if (sx126x_read_buffer(r,buffer.buffer_start_pointer,r->event.bytes,buffer.pld_len_in_bytes)!=SX126X_STATUS_OK)
        outcome=RADIO_FAILED;
    if (sx126x_handle_rx_done(r)!=SX126X_STATUS_OK) outcome=RADIO_FAILED;
    complete(r,outcome,observed);
}
