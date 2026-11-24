#pragma once
#include "radio/rf_frames.h"

typedef struct rf_reassembly rf_reassembly;
typedef rf_packet_port rf_reassembly_port;
typedef enum
{
    RF_REASSEMBLY_REJECTED,
    RF_REASSEMBLY_ACCEPTED,
    RF_REASSEMBLY_DUPLICATE,
    RF_REASSEMBLY_COMPLETE,
    RF_REASSEMBLY_CONFLICT,
    RF_REASSEMBLY_STALE,
    RF_REASSEMBLY_EXPIRED,
    RF_REASSEMBLY_HASH_FAILED,
    RF_REASSEMBLY_CANCELLED
} rf_reassembly_result;

rf_reassembly *rf_reassembly_create(rf_reassembly_port, uint64_t session, uint8_t source,
                                    uint8_t destination, uint16_t fragment_bytes);
void rf_reassembly_destroy(rf_reassembly *);
/* Hash and complete length are fixed before allocating a message buffer. */
bool rf_reassembly_begin(rf_reassembly *, uint32_t message, uint8_t content, uint8_t flags,
                         uint32_t message_bytes, const uint8_t sha256[32], int64_t now_us,
                         int64_t deadline_us);
/* Unprotected DATA only. GCM must be integrated before protected frames can enter. */
rf_reassembly_result rf_reassembly_accept(rf_reassembly *, const void *, size_t, int64_t now_us);
rf_reassembly_result rf_reassembly_poll(rf_reassembly *, int64_t now_us);
void rf_reassembly_cancel(rf_reassembly *);
/* Ascending missing indexes, paged by index; retained after failure/cancel. */
size_t rf_reassembly_missing(const rf_reassembly *, uint16_t first, uint16_t *out, size_t capacity);
/* Borrow once; pointer remains valid until begin/cancel/destroy. */
bool rf_reassembly_take(rf_reassembly *, const void **bytes, size_t *length, uint8_t sha256[32]);
