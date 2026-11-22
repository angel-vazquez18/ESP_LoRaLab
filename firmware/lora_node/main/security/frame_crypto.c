#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include "mbedtls/platform_util.h"
#include "psa/crypto.h"
#include "security/frame_crypto.h"

struct rf_crypto
{
    mbedtls_svc_key_id_t key;
};

static uint32_t be(const uint8_t *bytes, size_t count)
{
    uint32_t value = 0;
    for (size_t i = 0; i < count; i++)
        value = value << 8 | bytes[i];
    return value;
}

static bool header_valid(const uint8_t *h, size_t body)
{
    uint8_t type = h[3], flags = h[4];
    uint32_t count = be(h + 26, 2), total = be(h + 28, 4), reference = be(h + 34, 4);
    uint8_t session = 0;
    for (unsigned i = 8; i < 16; i++)
        session |= h[i];
    if (h[0] != 'L' || h[1] != 'T' || h[2] != 2 || type < 1 || type > 4 || !(flags & 1) ||
        (flags & ~3U) || h[5] < 1 || h[5] > 2 || h[6] < 1 || h[6] > 2 || h[5] == h[6] || h[7] > 1 ||
        !session || !be(h + 16, 4) || !be(h + 20, 4) || !count || count > 4096 ||
        be(h + 24, 2) >= count || !total || total > 65536 || body > RF_CRYPTO_MAX_BODY_BYTES ||
        body > total || be(h + 32, 2) != body || be(h + 38, 2))
        return false;
    if (type == 2)
        return !body && reference && !(flags & 2);
    if (!body)
        return false;
    if (type == 1)
        return !reference;
    return !h[7] && !(flags & 2) && count == 1 && total == body &&
           ((type == 3 && !reference) || (type == 4 && reference));
}

static rf_crypto_status backend_status(psa_status_t status)
{
    return status == PSA_ERROR_INSUFFICIENT_MEMORY ? RF_CRYPTO_NO_MEMORY : RF_CRYPTO_UNAVAILABLE;
}

rf_crypto_status rf_crypto_create(const uint8_t *key, size_t bytes, rf_crypto **owner)
{
    if (!key || bytes != RF_CRYPTO_KEY_BYTES || !owner || *owner)
        return RF_CRYPTO_INVALID_ARGUMENT;
    psa_status_t status = psa_crypto_init();
    if (status != PSA_SUCCESS)
        return backend_status(status);
    rf_crypto *context = calloc(1, sizeof(*context));
    if (!context)
        return RF_CRYPTO_NO_MEMORY;
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);
    psa_set_key_bits(&attributes, 128);
    psa_set_key_algorithm(&attributes, PSA_ALG_GCM);
    psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
    psa_set_key_lifetime(&attributes, PSA_KEY_LIFETIME_VOLATILE);
    status = psa_import_key(&attributes, key, bytes, &context->key);
    psa_reset_key_attributes(&attributes);
    if (status != PSA_SUCCESS)
    {
        mbedtls_platform_zeroize(context, sizeof(*context));
        free(context);
        return backend_status(status);
    }
    *owner = context;
    return RF_CRYPTO_OK;
}

rf_crypto_status rf_crypto_destroy(rf_crypto **owner)
{
    if (!owner)
        return RF_CRYPTO_INVALID_ARGUMENT;
    if (!*owner)
        return RF_CRYPTO_OK;
    psa_status_t status = psa_destroy_key((*owner)->key);
    if (status != PSA_SUCCESS)
        return backend_status(status); // Keep the handle for explicit cleanup recovery.
    mbedtls_platform_zeroize(*owner, sizeof(**owner));
    free(*owner);
    *owner = NULL;
    return RF_CRYPTO_OK;
}

rf_crypto_status rf_crypto_seal(rf_crypto *context, const uint8_t header[RF_CRYPTO_HEADER_BYTES],
                                const uint8_t *body, size_t bytes, uint8_t *frame, size_t capacity,
                                size_t *written)
{
    if (written)
        *written = 0;
    if (!context || !header || !frame || !written || (!body && bytes))
        return RF_CRYPTO_INVALID_ARGUMENT;
    if (!header_valid(header, bytes))
        return RF_CRYPTO_INVALID_FRAME;
    if (capacity < RF_CRYPTO_HEADER_BYTES + bytes + RF_CRYPTO_TAG_BYTES)
        return RF_CRYPTO_INVALID_ARGUMENT;
    uint8_t temporary[RF_CRYPTO_MAX_FRAME_BYTES] = {0};
    memcpy(temporary, header, RF_CRYPTO_HEADER_BYTES);
    size_t encrypted = 0;
    const uint8_t empty = 0;
    psa_status_t status = psa_aead_encrypt(context->key, PSA_ALG_GCM, temporary + 8, 12, temporary,
                                           RF_CRYPTO_HEADER_BYTES, bytes ? body : &empty, bytes,
                                           temporary + RF_CRYPTO_HEADER_BYTES,
                                           sizeof(temporary) - RF_CRYPTO_HEADER_BYTES, &encrypted);
    rf_crypto_status result = backend_status(status);
    if (status == PSA_SUCCESS && encrypted == bytes + RF_CRYPTO_TAG_BYTES)
    {
        memmove(frame, temporary, RF_CRYPTO_HEADER_BYTES + encrypted);
        *written = RF_CRYPTO_HEADER_BYTES + encrypted;
        result = RF_CRYPTO_OK;
    }
    mbedtls_platform_zeroize(temporary, sizeof(temporary));
    return result;
}

rf_crypto_status rf_crypto_open(rf_crypto *context, const uint8_t *frame, size_t bytes,
                                uint8_t *body, size_t capacity, size_t *written)
{
    if (written)
        *written = 0;
    if (!context || !frame || !written)
        return RF_CRYPTO_INVALID_ARGUMENT;
    if (bytes < RF_CRYPTO_HEADER_BYTES + RF_CRYPTO_TAG_BYTES || bytes > RF_CRYPTO_MAX_FRAME_BYTES)
        return RF_CRYPTO_INVALID_FRAME;
    size_t expected = bytes - RF_CRYPTO_HEADER_BYTES - RF_CRYPTO_TAG_BYTES;
    if (!header_valid(frame, expected))
        return RF_CRYPTO_INVALID_FRAME;
    if ((!body && expected) || capacity < expected)
        return RF_CRYPTO_INVALID_ARGUMENT;
    uint8_t temporary[RF_CRYPTO_MAX_BODY_BYTES] = {0};
    size_t decrypted = 0;
    psa_status_t status =
        psa_aead_decrypt(context->key, PSA_ALG_GCM, frame + 8, 12, frame, RF_CRYPTO_HEADER_BYTES,
                         frame + RF_CRYPTO_HEADER_BYTES, bytes - RF_CRYPTO_HEADER_BYTES, temporary,
                         sizeof(temporary), &decrypted);
    rf_crypto_status result =
        status == PSA_ERROR_INVALID_SIGNATURE ? RF_CRYPTO_AUTH_FAILED : backend_status(status);
    if (status == PSA_SUCCESS && decrypted == expected)
    {
        if (expected)
            memmove(body, temporary, expected);
        *written = expected;
        result = RF_CRYPTO_OK;
    }
    mbedtls_platform_zeroize(temporary, sizeof(temporary));
    return result;
}
