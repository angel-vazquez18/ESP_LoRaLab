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
int main(int argc, char **argv)
{
    fail_at = argc > 1 ? (unsigned)strtoul(argv[1], NULL, 10) : 0;
    codec2_frame_format format;
    bool ready = codec2_dependency_query(3200, &format);
    printf("ready=%u calls=%u live=%u peak=%zu\n", ready, calls, live, peak);
    if (live || retained || (fail_at && fail_at <= calls && ready))
        return 3;
    if ((!fail_at || fail_at > calls) && !ready)
        return 4;
    fail_at = calls = 0;
    ready = codec2_dependency_query(3200, &format);
    return !ready || live || retained ? 5 : 0;
}
