#pragma once
#include <stdbool.h>
#include "security/frame_crypto.h"

typedef struct rf_secure_session rf_secure_session;
rf_crypto_status rf_secure_create(uint64_t session, uint8_t role, const uint8_t tx_key[16],
                                  const uint8_t rx_key[16], rf_secure_session **owner);
bool rf_secure_ready(const rf_secure_session *);
// Reserved sequences are never returned to the pool, even if later work is cancelled.
rf_crypto_status rf_secure_reserve(rf_secure_session *, uint32_t count, uint32_t *first);
rf_crypto_status rf_secure_seal(rf_secure_session *, const uint8_t header[40], const uint8_t *body,
                                size_t bytes, uint8_t *frame, size_t capacity, size_t *written);
rf_crypto_status rf_secure_open(rf_secure_session *, const uint8_t *frame, size_t bytes,
                                uint8_t *body, size_t capacity, size_t *written);
// Disable access before attempting key destruction; failed cleanup retains ownership.
rf_crypto_status rf_secure_close(rf_secure_session **owner);
