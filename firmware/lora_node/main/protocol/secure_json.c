#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "protocol/secure_json.h"

typedef union
{
    max_align_t alignment;
    size_t bytes;
} allocation_header;

static secure_json_allocate_fn allocate_bytes;
static secure_json_release_fn release_bytes;
static bool installed;

static void *allocate(size_t bytes)
{
    if (bytes > SIZE_MAX - sizeof(allocation_header))
        return NULL;
    allocation_header *header = allocate_bytes(sizeof(*header) + bytes);
    if (!header)
        return NULL;
    memset(header, 0, sizeof(*header));
    header->bytes = bytes;
    return header + 1;
}

static void release(void *bytes)
{
    if (!bytes)
        return;
    allocation_header *header = (allocation_header *)bytes - 1;
    size_t length = sizeof(*header) + header->bytes;
    volatile uint8_t *value = (volatile uint8_t *)header;
    while (length--)
        *value++ = 0;
    release_bytes(header);
}

bool secure_json_install(secure_json_allocate_fn allocator, secure_json_release_fn deallocator)
{
    if ((allocator == NULL) != (deallocator == NULL))
        return false;
    if (!allocator)
    {
        allocator = malloc;
        deallocator = free;
    }
    if (installed)
        return allocator == allocate_bytes && deallocator == release_bytes;
    allocate_bytes = allocator;
    release_bytes = deallocator;
    cJSON_Hooks hooks = {.malloc_fn = allocate, .free_fn = release};
    cJSON_InitHooks(&hooks);
    installed = true;
    return true;
}

void secure_json_ensure(void)
{
    if (!installed)
        (void)secure_json_install(NULL, NULL);
}
