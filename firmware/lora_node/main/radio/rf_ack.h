#pragma once
#include "memory/buffers.h"
#include "radio/rf_frames.h"

typedef struct rf_ack_receiver rf_ack_receiver;
typedef enum
{
    RF_ACK_REJECTED,
    RF_ACK_NEW_DATA,
    RF_ACK_RETRY_DUPLICATE,
    RF_ACK_REPLAY
} rf_ack_classification;

rf_ack_receiver *rf_ack_create(rf_packet_port, uint64_t session, uint8_t local_role,
                               uint8_t peer_role, uint16_t fragment_bytes, uint32_t first_sequence,
                               uint32_t turnaround_us, uint32_t retry_horizon_us);
void rf_ack_destroy(rf_ack_receiver *);
/* Called only after framing/content validation and the receive/replay decision. */
bool rf_ack_offer(rf_ack_receiver *, const void *data, size_t frame_bytes, rf_ack_classification,
                  int64_t now_us);
/* Emits one due ACK, consuming a fresh local sequence. No DATA counters change. */
size_t rf_ack_take(rf_ack_receiver *, int64_t now_us, uint8_t out[56]);
void rf_ack_suppress(rf_ack_receiver *);
void rf_ack_cancel(rf_ack_receiver *);
bool rf_ack_matches(const void *ack, size_t ack_bytes, const void *outstanding_data,
                    size_t data_bytes, uint16_t fragment_bytes);

// Structural reference match only. Protected ACK authentication is the owner's responsibility.
bool rf_ack_header_matches(const uint8_t ack[40], const uint8_t data[40]);

void rf_ack_memory(const rf_ack_receiver *s, node_memory_inventory *out);
