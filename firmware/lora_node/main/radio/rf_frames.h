#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RF_HEADER_BYTES 40U
#define RF_SINGLE_BYTES 215U
typedef bool (*rf_hash)(void *, const void *, size_t, uint8_t[32]);
typedef struct
{
    uint64_t session;
    uint32_t seed, message_count, message_bytes, highest_message, highest_sequence;
    uint8_t source, destination;
} rf_single_receiver;
typedef struct
{
    uint64_t session;
    uint32_t frame_seq, message_id, message_bytes;
    uint8_t source, destination;
} rf_single_header;
typedef enum
{
    RF_DELIVERED,
    RF_DUPLICATE,
    RF_INVALID_FRAME,
    RF_WRONG_SESSION,
    RF_WRONG_ROLE,
    RF_WRONG_MESSAGE,
    RF_CONTENT_MISMATCH,
    RF_INTERNAL_ERROR,
    RF_STALE
} rf_acceptance;

size_t rf_single_encode(uint64_t session, uint32_t sequence, uint32_t message, uint8_t source,
                        uint8_t destination, const void *body, size_t length, uint8_t out[255]);
bool rf_single_decode(const uint8_t *, size_t, uint32_t fragment_bytes, rf_single_header *);
bool rf_known_data(rf_hash, void *, uint32_t seed, uint32_t message, void *out, size_t length);
rf_acceptance rf_single_accept(rf_single_receiver *, const uint8_t *, size_t,
                               uint32_t fragment_bytes, rf_hash, void *, uint8_t out[215],
                               uint8_t digest[32]);
