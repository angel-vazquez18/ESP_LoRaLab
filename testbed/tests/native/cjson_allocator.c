#include <stdatomic.h>
#include <stdlib.h>
#include "cJSON.h"

static atomic_long live, fail_after = -1;

static void *tracked_allocate(size_t bytes)
{
    long remaining = atomic_load(&fail_after);
    if (remaining >= 0 && atomic_fetch_sub(&fail_after, 1) == 0)
        return NULL;
    void *p = malloc(bytes);
    if (p)
        atomic_fetch_add(&live, 1);
    return p;
}
static void tracked_free(void *p)
{
    if (p)
        atomic_fetch_sub(&live, 1);
    free(p);
}
void native_allocator_install(void)
{
    cJSON_Hooks hooks = {.malloc_fn = tracked_allocate, .free_fn = tracked_free};
    cJSON_InitHooks(&hooks);
}
void native_allocator_fail_after(long allocations) { atomic_store(&fail_after, allocations); }
long native_allocations_live(void) { return atomic_load(&live); }
