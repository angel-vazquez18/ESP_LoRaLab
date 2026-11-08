#include <inttypes.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>

#include "esp_app_desc.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "psa/crypto.h"

#include "generated/contract_schema.h"
#include "platform/esp32_platform.h"

// Metadata is borrowed by the control engine for the firmware lifetime.
static char device_id[17], boot_id[32], reset_cause[32], elf_sha256[65];

static atomic_uint allocation_failures;

static void allocation_failed(size_t bytes, uint32_t caps, const char *function)
{
    (void)bytes;
    (void)caps;
    (void)function;
    atomic_fetch_add_explicit(&allocation_failures, 1, memory_order_relaxed);
}

static int64_t uptime(void *context)
{
    (void)context;
    return esp_timer_get_time();
}

static bool hash(void *context, const void *bytes, size_t length, uint8_t out[32])
{
    (void)context;
    size_t written = 0;
    return psa_hash_compute(PSA_ALG_SHA_256, bytes, length, out, 32, &written) == PSA_SUCCESS &&
           written == 32;
}

static void random_bytes(void *context, void *bytes, size_t length)
{
    (void)context;
    esp_fill_random(bytes, length);
}

static void *allocate(void *context, size_t bytes)
{
    (void)context;
    return heap_caps_malloc(bytes, MALLOC_CAP_8BIT);
}

static void deallocate(void *context, void *buffer)
{
    (void)context;
    heap_caps_free(buffer);
}

static node_heap heap(uint32_t caps)
{
    return (node_heap){
        .present = heap_caps_get_total_size(caps) != 0,
        .free_bytes = heap_caps_get_free_size(caps),
        .minimum_free_bytes = heap_caps_get_minimum_free_size(caps),
        .largest_free_bytes = heap_caps_get_largest_free_block(caps),
    };
}

static void memory(void *context, node_heap *internal, node_heap *psram, uint32_t *failures)
{
    (void)context;
    *internal = heap(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    *psram = heap(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    *failures = atomic_load_explicit(&allocation_failures, memory_order_relaxed);
}

void esp32_platform_init(node_platform *platform)
{
    ESP_ERROR_CHECK(psa_crypto_init() == PSA_SUCCESS ? ESP_OK : ESP_FAIL);
    ESP_ERROR_CHECK(heap_caps_register_failed_alloc_callback(allocation_failed));
    ESP_ERROR_CHECK(nvs_flash_init()); // Never erase identity automatically.

    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_efuse_mac_get_default(mac));

    snprintf(device_id, sizeof(device_id), "esp-%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2],
             mac[3], mac[4], mac[5]);

    nvs_handle_t storage;
    ESP_ERROR_CHECK(nvs_open("lora_diag", NVS_READWRITE, &storage));
    uint32_t boot_count = 0;
    esp_err_t err = nvs_get_u32(storage, "boot_count", &boot_count);
    ESP_ERROR_CHECK(err == ESP_ERR_NVS_NOT_FOUND ? ESP_OK : err);
    ESP_ERROR_CHECK(boot_count == UINT32_MAX ? ESP_ERR_INVALID_STATE : ESP_OK);
    ESP_ERROR_CHECK(nvs_set_u32(storage, "boot_count", ++boot_count));
    ESP_ERROR_CHECK(nvs_commit(storage));
    nvs_close(storage);

    snprintf(boot_id, sizeof(boot_id), "%s:%" PRIu32, device_id, boot_count);
    snprintf(reset_cause, sizeof(reset_cause), "esp_reset_reason_%d", esp_reset_reason());
    esp_app_get_elf_sha256(elf_sha256, sizeof(elf_sha256));
    const esp_app_desc_t *app = esp_app_get_description();
    *platform = (node_platform){
        .now_us = uptime,
        .sha256 = hash,
        .random_bytes = random_bytes,
        .allocate = allocate,
        .deallocate = deallocate,
        .memory = memory,
        .device_id = device_id,
        .boot_id = boot_id,
        .firmware_version = app->version,
        .firmware_build_id = elf_sha256,
        .idf_version = app->idf_ver,
        .board_manifest_hash = BOARD_PROFILE_SHA256,
        .schema_sha256 = CONTRACT_SCHEMA_SHA256,
        .reset_cause = reset_cause,
    };
}
