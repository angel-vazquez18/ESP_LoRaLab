#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RF_MESSAGE_BYTES 65536U
#define RF_MESSAGE_FRAGMENTS 4096U
#define RF_TAG_BYTES 16U

typedef struct
{
    uint64_t session;
    uint32_t first_sequence, message_id, message_bytes;
    uint16_t fragment_bytes, fragment_count;
    uint8_t source, destination, content, flags;
} rf_message_plan;

/* No allocation or radio activity; reserve all original sequences before work. */
bool rf_message_plan_init(rf_message_plan *, uint64_t session, uint32_t first_sequence,
                          uint32_t message_id, uint8_t source, uint8_t destination, uint8_t content,
                          bool protected_frame, bool ack_requested, uint32_t message_bytes,
                          uint16_t fragment_bytes);
/* Header only: protected bodies require authenticated encryption before transmission. */
size_t rf_message_header(const rf_message_plan *, uint16_t index, uint8_t out[40]);
/* Complete unprotected DATA; caller keeps the source immutable for the message lifetime. */
size_t rf_message_fragment(const rf_message_plan *, uint16_t index, const void *source,
                           size_t source_bytes, uint8_t out[255]);

typedef struct
{
    uint64_t session;
    uint32_t frame_sequence, message_id, message_bytes;
    uint16_t fragment_index, fragment_count, body_bytes;
    uint8_t source, destination, content, flags;
    const uint8_t *body;
} rf_data_view;
/* Validated unprotected view; its body borrows the caller's frame storage. */
bool rf_data_decode(const void *frame, size_t frame_bytes, uint16_t fragment_bytes, rf_data_view *);
