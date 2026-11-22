#pragma once
// Native checks use the pinned built-in AES/GCM; ESP-IDF selects its real drivers.
#define TF_PSA_CRYPTO_CONFIG_VERSION 0x01010000
#define PSA_WANT_ALG_GCM 1
#define PSA_WANT_ALG_SHA_256 1
#define PSA_WANT_KEY_TYPE_AES 1
#define MBEDTLS_PSA_CRYPTO_C
#define MBEDTLS_CTR_DRBG_C
#define MBEDTLS_PSA_BUILTIN_GET_ENTROPY
#define MBEDTLS_THREADING_C
#define MBEDTLS_THREADING_PTHREAD
