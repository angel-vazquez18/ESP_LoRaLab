#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CRYPTO_BENCH_PAGE 16U
#define CRYPTO_BENCH_WARMUPS 50U
#define CRYPTO_BENCH_MAX_ITERATIONS 10000U

typedef struct crypto_benchmark crypto_benchmark;
typedef struct {
    uint64_t start_us, end_us;
    bool checked;
} crypto_benchmark_sample;
typedef struct {
    unsigned path, phase, first_index, count;
    crypto_benchmark_sample samples[CRYPTO_BENCH_PAGE];
} crypto_benchmark_page;
typedef struct {
    uint32_t checked[4][3], pages_emitted, samples_lost;
    bool failed, finished;
} crypto_benchmark_status;

// Public-vector diagnostic only. It never borrows session keys or radio state.
crypto_benchmark *crypto_benchmark_create(unsigned payload, unsigned iterations,
                                          void *context, int64_t (*now_us)(void *));
void crypto_benchmark_step(crypto_benchmark *benchmark);
const crypto_benchmark_page *crypto_benchmark_pending(const crypto_benchmark *benchmark);
void crypto_benchmark_ack(crypto_benchmark *benchmark);
crypto_benchmark_status crypto_benchmark_progress(const crypto_benchmark *benchmark);
size_t crypto_benchmark_bytes(void);
bool crypto_benchmark_destroy(crypto_benchmark **benchmark);
