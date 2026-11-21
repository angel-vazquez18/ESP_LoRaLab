#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum { RADIO_BOARD_UNKNOWN, RADIO_HELTEC_V42_GC1109, RADIO_HELTEC_V43_KCT8103L } node_radio_variant;
typedef enum { RADIO_RESET, RADIO_FEM_POWER, RADIO_FEM_ENABLE, RADIO_FEM_MODE, RADIO_BUSY, RADIO_DIO1 } node_radio_signal;
typedef struct {
    void *context;
    int64_t (*now_us)(void *);
    void (*delay_us)(void *, uint32_t);
    bool (*set)(void *, node_radio_signal, bool);
    int (*get)(void *, node_radio_signal); // Negative means GPIO failure.
    bool (*transfer)(void *, const uint8_t *, uint8_t *, size_t);
} node_radio_bus;

typedef struct {
    uint32_t frequency_hz, bandwidth_hz;
    uint8_t spreading_factor, coding_rate_denominator;
    int8_t tx_power_dbm;
    uint8_t preamble_symbols;
} node_radio_settings;

typedef struct {
    uint64_t session_id;
    uint32_t frame_seq, message_id;
    uint16_t fragment_index;
    uint8_t attempt_index;
} node_radio_reference;
typedef enum { RADIO_DONE, RADIO_TIMEOUT, RADIO_CANCELLED, RADIO_FAILED, RADIO_CRC_ERROR, RADIO_HEADER_ERROR, RADIO_OVERSIZE } node_radio_outcome;
typedef enum { RADIO_EVENT_TX, RADIO_EVENT_RX } node_radio_event_kind;
typedef struct {
    node_radio_event_kind kind;
    node_radio_reference reference;
    node_radio_outcome status;
    uint16_t frame_bytes;
    int64_t command_us, done_us;
    bool crc_ok, signal_valid;
    float rssi_dbm, snr_db;
    uint8_t bytes[255];
} node_radio_event;

typedef struct {
    node_radio_bus bus;
    node_radio_variant variant;
    bool available;
    const char *error;
    bool configured, ldro_enabled;
    node_radio_settings applied;
    unsigned operation;
    uint16_t rx_maximum;
    bool event_pending;
    int64_t deadline_us;
    node_radio_event event;
} node_radio;

bool node_radio_init(node_radio *, const node_radio_bus *, node_radio_variant);
bool node_radio_stop(node_radio *);
bool node_radio_valid_settings(const node_radio_settings *);
bool node_radio_configure(node_radio *, const node_radio_settings *);
// True means accepted; poll reports observed completion/failure exactly once.
bool node_radio_tx(node_radio *, const uint8_t *, size_t, const node_radio_reference *, uint32_t timeout_us);
bool node_radio_rx(node_radio *, size_t max_frame_bytes, uint32_t timeout_us);
bool node_radio_poll(node_radio *, node_radio_event *);
const char *node_radio_variant_name(node_radio_variant);
