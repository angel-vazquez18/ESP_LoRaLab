#include <stdatomic.h>
#include <stdlib.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "protocol/secure_json.h"

static atomic_long live, fail_after = -1, secret_frees;
static unsigned char needle[64];
static size_t needle_bytes;
typedef union
{
    max_align_t alignment;
    size_t bytes;
} allocation_header;

static void *tracked_allocate(size_t bytes)
{
    long remaining = atomic_load(&fail_after);
    if (remaining >= 0 && atomic_fetch_sub(&fail_after, 1) == 0)
        return NULL;
    if (bytes > SIZE_MAX - sizeof(allocation_header))
        return NULL;
    allocation_header *p = malloc(sizeof(*p) + bytes);
    if (p)
    {
        p->bytes = bytes;
        atomic_fetch_add(&live, 1);
    }
    return p ? p + 1 : NULL;
}
static void tracked_free(void *p)
{
    if (!p)
        return;
    allocation_header *header = (allocation_header *)p - 1;
    if (needle_bytes && header->bytes >= needle_bytes)
    {
        for (size_t i = 0; i <= header->bytes - needle_bytes; i++)
            if (!memcmp((unsigned char *)p + i, needle, needle_bytes))
            {
                atomic_fetch_add(&secret_frees, 1);
                break;
            }
    }
    atomic_fetch_sub(&live, 1);
    free(header);
}
void native_allocator_install(void) { (void)secure_json_install(tracked_allocate, tracked_free); }
void native_allocator_fail_after(long allocations) { atomic_store(&fail_after, allocations); }
long native_allocations_live(void) { return atomic_load(&live); }

void native_watch_secret(const void *value, size_t length)
{
    needle_bytes = length <= sizeof(needle) ? length : 0;
    if (needle_bytes)
        memcpy(needle, value, needle_bytes);
    atomic_store(&secret_frees, 0);
}
long native_secret_frees(void) { return atomic_load(&secret_frees); }
