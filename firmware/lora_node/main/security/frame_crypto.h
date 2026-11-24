#pragma once
#include <stddef.h>
#include <stdint.h>

#define RF_CRYPTO_HEADER_BYTES 40U
#define RF_CRYPTO_KEY_BYTES 16U
#define RF_CRYPTO_TAG_BYTES 16U
#define RF_CRYPTO_MAX_BODY_BYTES 199U
#define RF_CRYPTO_MAX_FRAME_BYTES 255U

typedef struct rf_crypto rf_crypto;
typedef enum
{
    RF_CRYPTO_OK,
    RF_CRYPTO_INVALID_ARGUMENT,
    RF_CRYPTO_INVALID_FRAME,
    RF_CRYPTO_AUTH_FAILED,
    RF_CRYPTO_UNAVAILABLE,
    RF_CRYPTO_NO_MEMORY,
    RF_CRYPTO_NONCE_EXHAUSTED,
    RF_CRYPTO_SESSION_CLOSED
} rf_crypto_status;

// Keys are imported as volatile, non-exportable PSA handles; *owner starts NULL.
rf_crypto_status rf_crypto_create(const uint8_t *key, size_t key_bytes, rf_crypto **owner);
// Failure preserves ownership so the caller can quarantine/retry cleanup.
rf_crypto_status rf_crypto_destroy(rf_crypto **owner);
// Nonce is header[8:20]. Caller owns unique sequences; retries use retained bytes.
rf_crypto_status rf_crypto_seal(rf_crypto *, const uint8_t header[RF_CRYPTO_HEADER_BYTES],
                                const uint8_t *body, size_t body_bytes, uint8_t *frame,
                                size_t capacity, size_t *written);
// Output is unchanged on failure; *written is zero. No plaintext before verified tag.
rf_crypto_status rf_crypto_open(rf_crypto *, const uint8_t *frame, size_t frame_bytes,
                                uint8_t *body, size_t capacity, size_t *written);
