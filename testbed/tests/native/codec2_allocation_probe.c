#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "codec2_dependency.h"

typedef union { max_align_t align; size_t size; } allocation;
static unsigned calls, fail_at, live;
static size_t retained, peak;

void *codec_test_malloc(size_t size)
{
    if (++calls == fail_at)
        return NULL;
    allocation *block = malloc(sizeof(*block) + size);
    if (!block)
        return NULL;
    block->size = size;
    live++;
    retained += size;
    if (retained > peak)
        peak = retained;
    return block + 1;
}
void *codec_test_calloc(size_t count, size_t size)
{
    if (size && count > SIZE_MAX / size)
        return NULL;
    void *result = codec_test_malloc(count * size);
    if (result)
        memset(result, 0, count * size);
    return result;
}
void codec_test_free(void *pointer)
{
    if (!pointer)
        return;
    allocation *block = (allocation *)pointer - 1;
    retained -= block->size;
    live--;
    free(block);
}
static bool decoder_probe(void)
{
    codec2_clip_state *state = codec2_clip_create();
    if (!state) return false;
    short samples[160];
    uint8_t bits[8] = {0};
    bool decoded = codec2_decode_frame(state, bits, sizeof(bits), samples, 160);
    codec2_clip_destroy(state);
    return decoded;
}

int main(int argc, char **argv)
{
    fail_at = argc > 1 ? (unsigned)strtoul(argv[1], NULL, 10) : 0;
    codec2_frame_format format;
    bool decoder = argc > 2 && !strcmp(argv[2], "decode");
    bool ready = decoder ? decoder_probe() : codec2_dependency_query(3200, &format);
    printf("ready=%u calls=%u live=%u peak=%zu\n", ready, calls, live, peak);
    if (live || retained || (fail_at && fail_at <= calls && ready))
        return 3;
    if ((!fail_at || fail_at > calls) && !ready)
        return 4;
    fail_at = calls = 0;
    ready = decoder ? decoder_probe() : codec2_dependency_query(3200, &format);
    return !ready || live || retained ? 5 : 0;
}
