#include <stdlib.h>
#include <string.h>
#include "mbedtls/platform_util.h"
#include "security/session_crypto.h"

struct rf_secure_session
{
    rf_crypto *tx, *rx;
    uint64_t session;
    uint32_t reserved, sealed;
    uint8_t role;
    bool active;
};

static uint64_t integer(const uint8_t *bytes, size_t count)
{
    uint64_t value = 0;
    for (size_t i = 0; i < count; i++)
        value = value << 8 | bytes[i];
    return value;
}

bool rf_secure_ready(const rf_secure_session *session) { return session && session->active; }

rf_crypto_status rf_secure_close(rf_secure_session **owner)
{
    if (!owner)
        return RF_CRYPTO_INVALID_ARGUMENT;
    if (!*owner)
        return RF_CRYPTO_OK;
    rf_secure_session *session = *owner;
    session->active = false;
    rf_crypto_status tx = rf_crypto_destroy(&session->tx);
    rf_crypto_status rx = rf_crypto_destroy(&session->rx);
    if (tx != RF_CRYPTO_OK || rx != RF_CRYPTO_OK)
        return tx != RF_CRYPTO_OK ? tx : rx;
    mbedtls_platform_zeroize(session, sizeof(*session));
    free(session);
    *owner = NULL;
    return RF_CRYPTO_OK;
}

rf_crypto_status rf_secure_create(uint64_t id, uint8_t role, const uint8_t tx_key[16],
                                  const uint8_t rx_key[16], rf_secure_session **owner)
{
    if (!id || (role != 1 && role != 2) || !tx_key || !rx_key || !owner || *owner ||
        !memcmp(tx_key, rx_key, 16))
        return RF_CRYPTO_INVALID_ARGUMENT;
    rf_secure_session *session = calloc(1, sizeof(*session));
    if (!session)
        return RF_CRYPTO_NO_MEMORY;
    *owner = session; // Preserve a quarantined owner if partial cleanup fails.
    rf_crypto_status result = rf_crypto_create(tx_key, 16, &session->tx);
    if (result == RF_CRYPTO_OK)
        result = rf_crypto_create(rx_key, 16, &session->rx);
    if (result != RF_CRYPTO_OK)
    {
        rf_crypto_status cleanup = rf_secure_close(owner);
        return cleanup == RF_CRYPTO_OK ? result : cleanup;
    }
    session->session = id;
    session->role = role;
    session->active = true;
    return RF_CRYPTO_OK;
}

rf_crypto_status rf_secure_reserve(rf_secure_session *session, uint32_t count, uint32_t *first)
{
    if (first)
        *first = 0;
    if (!first || !count)
        return RF_CRYPTO_INVALID_ARGUMENT;
    if (!rf_secure_ready(session))
        return RF_CRYPTO_SESSION_CLOSED;
    if ((uint64_t)session->reserved + count > UINT32_MAX)
        return RF_CRYPTO_NONCE_EXHAUSTED;
    *first = session->reserved + 1;
    session->reserved += count;
    return RF_CRYPTO_OK;
}

static bool bound(const rf_secure_session *session, const uint8_t *header, bool transmit)
{
    uint8_t source = transmit ? session->role : 3 - session->role;
    return header && integer(header + 8, 8) == session->session && header[5] == source &&
           header[6] == 3 - source;
}

rf_crypto_status rf_secure_seal(rf_secure_session *session, const uint8_t header[40],
                                const uint8_t *body, size_t bytes, uint8_t *frame, size_t capacity,
                                size_t *written)
{
    if (written)
        *written = 0;
    if (!rf_secure_ready(session))
        return RF_CRYPTO_SESSION_CLOSED;
    if (!written || !bound(session, header, true))
        return RF_CRYPTO_INVALID_ARGUMENT;
    uint32_t sequence = integer(header + 16, 4);
    if (!sequence || sequence <= session->sealed || sequence > session->reserved)
        return RF_CRYPTO_INVALID_ARGUMENT;
    session->sealed = sequence; // Burn before calling the cipher; never roll it back.
    rf_crypto_status result =
        rf_crypto_seal(session->tx, header, body, bytes, frame, capacity, written);
    if (result == RF_CRYPTO_UNAVAILABLE || result == RF_CRYPTO_NO_MEMORY)
        session->active = false;
    return result;
}

rf_crypto_status rf_secure_open(rf_secure_session *session, const uint8_t *frame, size_t bytes,
                                uint8_t *body, size_t capacity, size_t *written)
{
    if (written)
        *written = 0;
    if (!rf_secure_ready(session))
        return RF_CRYPTO_SESSION_CLOSED;
    if (!written || !frame || bytes < 56 || bytes > 255 || !bound(session, frame, false))
        return RF_CRYPTO_INVALID_ARGUMENT;
    rf_crypto_status result = rf_crypto_open(session->rx, frame, bytes, body, capacity, written);
    if (result == RF_CRYPTO_UNAVAILABLE || result == RF_CRYPTO_NO_MEMORY)
        session->active = false;
    return result;
}
