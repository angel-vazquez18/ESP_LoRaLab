#pragma once
#include "memory/buffers.h"
#include "radio/node_radio.h"
#include "radio/rf_frames.h"
#include "radio/rf_faults.h"
#include "security/session_crypto.h"

typedef struct rf_sender rf_sender;
typedef enum
{
    RF_SENDER_READY,
    RF_SENDER_TX,
    RF_SENDER_ACK,
    RF_SENDER_GUARD,
    RF_SENDER_COMPLETED,
    RF_SENDER_FAILED,
    RF_SENDER_CANCELLED
} rf_sender_state;
typedef struct
{
    uint32_t state, originals, attempts, acks, rejected_acks;
    int64_t ack_deadline_us, retry_at_us;
    const char *reason;
    uint32_t last_ack_acceptance;
} rf_sender_status;

uint32_t rf_radio_airtime_us(const node_radio_settings *, size_t frame_bytes);
rf_sender *rf_sender_create(rf_packet_port, node_radio *);
void rf_sender_destroy(rf_sender *);
/* Validate budget and copy immutable DATA before RF; one outstanding frame. */
bool rf_sender_begin(rf_sender *, const void *frame, size_t frame_bytes, uint16_t fragment_bytes,
                     uint8_t max_retries, uint32_t guard_us, uint32_t ack_turnaround_us,
                     uint32_t ack_margin_us, int64_t run_deadline_us);
/* One retained radio observation; a blocked consumer prevents further attempts. */
bool rf_sender_poll(rf_sender *, node_radio_event *observation);
void rf_sender_snapshot(const rf_sender *, rf_sender_status *);
void rf_sender_cancel(rf_sender *);

// Borrow a session owner before beginning work; retained retries never invoke seal.
bool rf_sender_security(rf_sender *, rf_secure_session *);
bool rf_sender_faults(rf_sender *, rf_faults *);

void rf_sender_memory(const rf_sender *s, node_memory_inventory *out);
