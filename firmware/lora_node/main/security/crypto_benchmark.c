#include <stdlib.h>
#include <string.h>
#include "mbedtls/platform_util.h"
#include "psa/crypto.h"
#include "security/crypto_benchmark.h"
#include "generated/crypto_benchmark_vectors.h"

struct crypto_benchmark {
    mbedtls_svc_key_id_t key;
    void *context;
    int64_t (*now_us)(void *);
    const crypto_benchmark_vector *vector;
    unsigned iterations, path, phase, index;
    uint8_t output[215], invalid[215];
    crypto_benchmark_page page;
    crypto_benchmark_status status;
};

crypto_benchmark *crypto_benchmark_create(unsigned payload, unsigned iterations,
                                          void *context, int64_t (*now_us)(void *))
{
    if (!now_us || !iterations || iterations > CRYPTO_BENCH_MAX_ITERATIONS) return NULL;
    const crypto_benchmark_vector *vector = NULL;
    for (unsigned i = 0; i < 4; i++)
        if (crypto_benchmark_vectors[i].bytes == payload) vector = &crypto_benchmark_vectors[i];
    if (!vector || psa_crypto_init() != PSA_SUCCESS) return NULL;
    crypto_benchmark *b = calloc(1, sizeof(*b));
    if (!b) return NULL;
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);
    psa_set_key_bits(&attributes, 128);
    psa_set_key_algorithm(&attributes, PSA_ALG_GCM);
    psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
    psa_set_key_lifetime(&attributes, PSA_KEY_LIFETIME_VOLATILE);
    psa_status_t status = psa_import_key(&attributes, crypto_benchmark_public_key, 16, &b->key);
    psa_reset_key_attributes(&attributes);
    if (status != PSA_SUCCESS) { free(b); return NULL; }
    b->context = context; b->now_us = now_us; b->vector = vector; b->iterations = iterations;
    memcpy(b->invalid, vector->protected_bytes, payload + 16);
    b->invalid[payload + 15] ^= 1;
    return b;
}

static unsigned phase_count(const crypto_benchmark *b)
{
    return b->phase == 0 ? 1 : b->phase == 1 ? CRYPTO_BENCH_WARMUPS : b->iterations;
}

void crypto_benchmark_step(crypto_benchmark *b)
{
    if (!b || b->status.finished || b->status.failed ||
        (b->page.count && (b->page.path != b->path || b->page.phase != b->phase)) ||
        b->page.count == CRYPTO_BENCH_PAGE) return;
    const crypto_benchmark_vector *v = b->vector;
    if (!b->page.count) {
        b->page.path = b->path; b->page.phase = b->phase; b->page.first_index = b->index;
    }
    memset(b->output, 0xa5, sizeof(b->output));
    size_t written = 0;
    psa_status_t status = PSA_ERROR_GENERIC_ERROR;
    int64_t start, end;
    if (b->path == 0) {
        // Only the real one-shot PSA call is inside the pair of timestamps.
        start = b->now_us(b->context);
        status = psa_aead_encrypt(b->key, PSA_ALG_GCM, v->header + 8, 12, v->header, 40,
            v->plain, v->bytes, b->output, sizeof(b->output), &written);
        end = b->now_us(b->context);
    } else if (b->path < 3) {
        const uint8_t *input = b->path == 1 ? v->protected_bytes : b->invalid;
        start = b->now_us(b->context);
        status = psa_aead_decrypt(b->key, PSA_ALG_GCM, v->header + 8, 12, v->header, 40,
            input, v->bytes + 16,
            b->output, sizeof(b->output), &written);
        end = b->now_us(b->context);
    } else {
        start = b->now_us(b->context);
        memcpy(b->output, v->protected_bytes, v->bytes + 16);
        end = b->now_us(b->context);
    }
    bool checked = b->path == 0 ? status == PSA_SUCCESS && written == v->bytes + 16 &&
            !memcmp(b->output, v->protected_bytes, written) :
        b->path == 1 ? status == PSA_SUCCESS && written == v->bytes &&
            !memcmp(b->output, v->plain, written) :
        b->path == 2 ? status == PSA_ERROR_INVALID_SIGNATURE && written == 0 :
            !memcmp(b->output, v->protected_bytes, v->bytes + 16);
    checked = checked && start >= 0 && end >= start;
    b->page.samples[b->page.count++] = (crypto_benchmark_sample){start < 0 ? 0 : (uint64_t)start,
        end < start || end < 0 ? (uint64_t)(start < 0 ? 0 : start) : (uint64_t)end, checked};
    if (checked) b->status.checked[b->path][b->phase]++;
    else b->status.failed = true;
    mbedtls_platform_zeroize(b->output, sizeof(b->output));
    if (++b->index == phase_count(b)) {
        b->index = 0;
        if (++b->phase == 3) { b->phase = 0; if (++b->path == 4) b->status.finished = true; }
    }
}
const crypto_benchmark_page *crypto_benchmark_pending(const crypto_benchmark *b)
{
    return b && b->page.count ? &b->page : NULL;
}
void crypto_benchmark_ack(crypto_benchmark *b)
{
    if (b && b->page.count) { b->status.pages_emitted++; b->page.count = 0; }
}
crypto_benchmark_status crypto_benchmark_progress(const crypto_benchmark *b)
{
    return b ? b->status : (crypto_benchmark_status){0};
}
size_t crypto_benchmark_bytes(void) { return sizeof(crypto_benchmark); }
bool crypto_benchmark_destroy(crypto_benchmark **b)
{
    if (!b) return false;
    if (!*b) return true;
    if (psa_destroy_key((*b)->key) != PSA_SUCCESS) return false;
    mbedtls_platform_zeroize(*b, sizeof(**b)); free(*b); *b = NULL; return true;
}

void crypto_benchmark_memory(const crypto_benchmark *s, node_memory_inventory *out)
{
    if (!s) return;
    node_memory_add(out, "crypto_benchmark", s, sizeof(*s));
}
