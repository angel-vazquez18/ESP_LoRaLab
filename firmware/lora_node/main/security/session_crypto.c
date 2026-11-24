#include "security/session_crypto.h"
#include "mbedtls/platform_util.h"
#include "psa/crypto.h"
#include <stdlib.h>
#include <string.h>

struct rf_secure_session
{
    rf_crypto *tx, *rx;
    uint64_t session;
    uint32_t reserved, sealed;
    uint8_t role;
    bool active;
    uint32_t highest_received;
    uint8_t replay_bits[16], cache_next;
    struct
    {
        uint32_t sequence;
        uint8_t digest[32];
        int64_t received_us, expires_us;
    } accepted_data[16];
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

static bool seen(const rf_secure_session *s, unsigned offset)
{
    return (s->replay_bits[offset / 8] & (1U << (offset % 8))) != 0;
}
static void set_seen(rf_secure_session *s, unsigned offset, bool value)
{
    uint8_t mask = 1U << (offset % 8);
    if (value)
        s->replay_bits[offset / 8] |= mask;
    else
        s->replay_bits[offset / 8] &= (uint8_t)~mask;
}
static void commit_received(rf_secure_session *s, uint32_t sequence)
{
    if (sequence > s->highest_received)
    {
        uint32_t distance = sequence - s->highest_received;
        if (distance >= 128)
            memset(s->replay_bits, 0, sizeof(s->replay_bits));
        else
            for (int i = 127; i >= 0; i--)
                set_seen(s, i, (unsigned)i >= distance && seen(s, (unsigned)i - distance));
        s->highest_received = sequence;
    }
    set_seen(s, s->highest_received - sequence, true);
}
rf_secure_acceptance rf_secure_receive(rf_secure_session *s, const uint8_t *frame, size_t bytes,
                                       int64_t now, bool ack_mode, uint32_t horizon,
                                       rf_secure_insert insert, void *context)
{
    if (!rf_secure_ready(s))
        return RF_SECURE_UNAVAILABLE;
    if (!insert || now < 0 || horizon > 3600000000U || (ack_mode && !horizon) ||
        now > INT64_MAX - horizon)
        return RF_SECURE_REJECTED;
    uint8_t plain[199] = {0}, digest[32] = {0};
    size_t written = 0;
    rf_crypto_status opened = rf_secure_open(s, frame, bytes, plain, sizeof(plain), &written);
    rf_secure_acceptance result = RF_SECURE_REJECTED;
    if (opened != RF_CRYPTO_OK)
    {
        result = opened == RF_CRYPTO_AUTH_FAILED ? RF_SECURE_AUTH_FAILED
                 : opened == RF_CRYPTO_UNAVAILABLE || opened == RF_CRYPTO_NO_MEMORY ||
                         opened == RF_CRYPTO_SESSION_CLOSED
                     ? RF_SECURE_UNAVAILABLE
                     : RF_SECURE_REJECTED;
        goto done;
    }
    uint32_t sequence = integer(frame + 16, 4);
    if (sequence <= s->highest_received && s->highest_received - sequence >= 128)
    {
        result = RF_SECURE_TOO_OLD;
        goto done;
    }
    bool duplicate = sequence <= s->highest_received && seen(s, s->highest_received - sequence);
    bool retry_eligible = ack_mode && frame[3] == 1 && (frame[4] & 2);
    if (duplicate && !retry_eligible)
    {
        result = RF_SECURE_REPLAY;
        goto done;
    }
    if (retry_eligible)
    {
        size_t hashed = 0;
        if (psa_hash_compute(PSA_ALG_SHA_256, frame, bytes, digest, sizeof(digest), &hashed) !=
                PSA_SUCCESS ||
            hashed != sizeof(digest))
        {
            s->active = false;
            result = RF_SECURE_UNAVAILABLE;
            goto done;
        }
    }
    if (duplicate)
    {
        result = RF_SECURE_REPLAY;
        for (unsigned i = 0; i < 16; i++)
            if (s->accepted_data[i].sequence == sequence &&
                now >= s->accepted_data[i].received_us && now < s->accepted_data[i].expires_us &&
                !memcmp(digest, s->accepted_data[i].digest, sizeof(digest)))
            {
                result = RF_SECURE_RETRY_DUPLICATE;
                break;
            }
        goto done; // Never call insertion again, and never extend the original retry horizon.
    }
    if (!insert(context, frame, plain, written))
        goto done;
    commit_received(s, sequence);
    if (retry_eligible)
    {
        unsigned entry = s->cache_next;
        s->cache_next = (s->cache_next + 1) % 16;
        s->accepted_data[entry].sequence = sequence;
        s->accepted_data[entry].received_us = now;
        s->accepted_data[entry].expires_us = now + horizon;
        memcpy(s->accepted_data[entry].digest, digest, sizeof(digest));
    }
    result = RF_SECURE_ACCEPTED;
done:
    mbedtls_platform_zeroize(plain, sizeof(plain));
    mbedtls_platform_zeroize(digest, sizeof(digest));
    return result;
}

void rf_secure_memory(const rf_secure_session *s, node_memory_inventory *out)
{
    if (!s) return;
    node_memory_add(out, "session_security", s, sizeof(*s));
    rf_crypto_memory(s->tx, "crypto_tx_owner", out);
    rf_crypto_memory(s->rx, "crypto_rx_owner", out);
}
