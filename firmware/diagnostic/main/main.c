/* Contract 2.0 diagnostic target. No radio, audio or session keys are enabled.
 */
#include "cJSON.h"
#include "contract_schema.h"
#include "driver/usb_serial_jtag.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "psa/crypto.h"
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_RECORD 4096
#define CACHE_COUNT 16
static char device_id[32], boot_id[96], owner[97], role[2];
static int64_t lease_until;
static uint32_t high_sequence;
static uint64_t event_sequence, telemetry_drops;
static uint32_t allocation_failures;
typedef struct {
  uint32_t seq;
  uint8_t hash[32];
  char client[97];
  char command[97];
  char reply[1024];
} cached_reply;
static cached_reply cache[CACHE_COUNT];
static unsigned cache_next;

static void add_s(cJSON *o, const char *key, const char *s) {
  if (s)
    cJSON_AddStringToObject(o, key, s);
  else
    cJSON_AddNullToObject(o, key);
}
static void add_n(cJSON *o, const char *key, double n) {
  cJSON_AddNumberToObject(o, key, n);
}
static void add_b(cJSON *o, const char *key, bool b) {
  cJSON_AddBoolToObject(o, key, b);
}
static const char *str(cJSON *o, const char *key) {
  return cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, key));
}
static bool equal(const char *a, const char *b) {
  return a && b && strcmp(a, b) == 0;
}
static cJSON *caps(void) {
  cJSON *o = cJSON_CreateObject();
  const char *disabled[] = {"radio",          "audio_capture", "audio_playback",
                            "codec2_3200",    "security_gcm",  "fragmentation",
                            "ack_retry",      "echo",          "clock_sync",
                            "fault_injection"};
  for (unsigned i = 0; i < sizeof(disabled) / sizeof(disabled[0]); i++)
    add_b(o, disabled[i], false);
  add_b(o, "memory_stats", true);
  cJSON_AddItemToObject(o, "radio_limits", cJSON_CreateObject());
  cJSON *limits = cJSON_CreateObject();
  add_n(limits, "max_record_bytes", MAX_RECORD);
  cJSON_AddItemToObject(o, "resource_limits", limits);
  add_n(o, "timestamp_resolution_us", 1);
  return o;
}
static cJSON *heap(uint32_t capability) {
  if (heap_caps_get_total_size(capability) == 0)
    return cJSON_CreateNull();
  cJSON *o = cJSON_CreateObject();
  add_n(o, "free_bytes", heap_caps_get_free_size(capability));
  add_n(o, "minimum_free_bytes", heap_caps_get_minimum_free_size(capability));
  add_n(o, "largest_free_bytes", heap_caps_get_largest_free_block(capability));
  return o;
}
static cJSON *health(void) {
  cJSON *o = cJSON_CreateObject(), *m = cJSON_CreateObject();
  add_s(o, "node_role", role[0] ? role : NULL);
  add_s(o, "state", "idle");
  add_s(o, "run_id", NULL);
  add_s(o, "operation_id", NULL);
  add_n(o, "uptime_us", esp_timer_get_time());
  char reset[32];
  snprintf(reset, sizeof(reset), "esp_reset_reason_%d", esp_reset_reason());
  add_s(o, "reset_cause", reset);
  add_s(o, "radio", NULL);
  add_s(o, "link", NULL);
  add_n(o, "config_revision", 0);
  cJSON_AddItemToObject(o, "capability_availability", caps());
  cJSON_AddItemToObject(m, "internal",
                        heap(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  cJSON_AddItemToObject(m, "psram", heap(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  cJSON_AddItemToObject(m, "buffers", cJSON_CreateObject());
  add_n(m, "allocation_failures", allocation_failures);
  cJSON_AddItemToObject(o, "memory", m);
  cJSON_AddItemToObject(o, "traffic", cJSON_CreateObject());
  add_b(o, "security_ready", false);
  add_s(o, "audio_state", "not_supported");
  add_n(o, "telemetry_drops", telemetry_drops);
  add_s(o, "last_error", NULL);
  add_s(o, "last_rx", NULL);
  return o;
}
static cJSON *hello(void) {
  cJSON *o = cJSON_CreateObject();
  const esp_app_desc_t *app = esp_app_get_description();
  add_s(o, "device_id", device_id);
  add_s(o, "boot_id", boot_id);
  add_s(o, "board_model", NULL);
  add_s(o, "board_revision", NULL);
  add_s(o, "chip_model", "ESP32-S3");
  add_s(o, "firmware_version", app->version);
  add_s(o, "firmware_commit", NULL);
  char build[65];
  for (int i = 0; i < 32; i++)
    snprintf(build + i * 2, 3, "%02x", app->app_elf_sha256[i]);
  add_s(o, "firmware_build_id", build);
  add_s(o, "idf_version", app->idf_ver);
  add_s(o, "board_manifest_hash", NULL);
  add_s(o, "provenance", "hardware");
  cJSON *versions = cJSON_CreateArray();
  cJSON_AddItemToArray(versions, cJSON_CreateNumber(2));
  cJSON_AddItemToObject(o, "supported_wire_versions", versions);
  add_s(o, "contract_version", "2.0.0");
  add_s(o, "schema_sha256", CONTRACT_SCHEMA_SHA256);
  cJSON_AddItemToObject(o, "capabilities", caps());
  add_b(o, "claimed", owner[0] != 0);
  add_s(o, "state", "idle");
  return o;
}
static bool send_text(const char *text) {
  size_t length = strlen(text), sent = 0;
  if (length + 1 > MAX_RECORD)
    return false;
  while (sent < length) {
    int n = usb_serial_jtag_write_bytes(text + sent, length - sent,
                                        pdMS_TO_TICKS(100));
    if (n <= 0)
      return false;
    sent += (size_t)n;
  }
  if (usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(100)) != 1)
    return false;
  return true;
}
static char *reply(cJSON *cmd, cJSON *result, const char *code,
                   const char *message) {
  cJSON *o = cJSON_CreateObject();
  add_n(o, "v", 2);
  add_s(o, "kind", "reply");
  add_s(o, "command_id", str(cmd, "command_id"));
  add_n(o, "command_seq",
        cJSON_GetNumberValue(cJSON_GetObjectItem(cmd, "command_seq")));
  add_s(o, "device_id", device_id);
  add_s(o, "boot_id", boot_id);
  add_n(o, "uptime_us", esp_timer_get_time());
  add_b(o, "ok", code == NULL);
  cJSON_AddItemToObject(o, "result", result ? result : cJSON_CreateNull());
  if (code) {
    cJSON *e = cJSON_CreateObject();
    add_s(e, "code", code);
    add_s(e, "message", message);
    add_s(e, "field", NULL);
    add_b(e, "retryable", false);
    cJSON_AddItemToObject(o, "error", e);
  } else
    add_s(o, "error", NULL);
  char *encoded = cJSON_PrintUnformatted(o);
  cJSON_Delete(o);
  return encoded;
}
static bool valid_tree(cJSON *value, unsigned depth) {
  if (depth > 8 && (cJSON_IsObject(value) || cJSON_IsArray(value)))
    return false;
  for (cJSON *a = value->child; a; a = a->next) {
    if (cJSON_IsObject(value))
      for (cJSON *b = a->next; b; b = b->next)
        if (equal(a->string, b->string))
          return false;
    if (!valid_tree(a, depth + 1))
      return false;
  }
  return true;
}
static bool valid_envelope(cJSON *o) {
  const char *keys[] = {"v",         "kind",        "command_id",
                        "client_id", "command_seq", "target_boot_id",
                        "run_id",    "name",        "args"};
  if (!cJSON_IsObject(o) || !valid_tree(o, 0) || cJSON_GetArraySize(o) != 9)
    return false;
  for (unsigned i = 0; i < 9; i++)
    if (!cJSON_HasObjectItem(o, keys[i]))
      return false;
  double seq = cJSON_GetNumberValue(cJSON_GetObjectItem(o, "command_seq"));
  return cJSON_GetNumberValue(cJSON_GetObjectItem(o, "v")) == 2 &&
         equal(str(o, "kind"), "command") && str(o, "command_id") &&
         strlen(str(o, "command_id")) > 0 &&
         strlen(str(o, "command_id")) <= 96 && str(o, "client_id") &&
         strlen(str(o, "client_id")) > 0 && strlen(str(o, "client_id")) <= 96 &&
         str(o, "name") && strlen(str(o, "name")) > 0 &&
         strlen(str(o, "name")) <= 64 && seq >= 1 && seq <= UINT32_MAX &&
         seq == (uint32_t)seq && cJSON_IsObject(cJSON_GetObjectItem(o, "args"));
}
static bool valid_utf8(const unsigned char *s, size_t length) {
  for (size_t i = 0; i < length;) {
    unsigned c = s[i++], count = 0, min = 0;
    uint32_t value;
    if (c == 0)
      return false;
    if (c < 0x80)
      continue;
    if (c >= 0xc2 && c <= 0xdf) {
      count = 1;
      min = 0x80;
      value = c & 0x1f;
    } else if (c >= 0xe0 && c <= 0xef) {
      count = 2;
      min = 0x800;
      value = c & 0x0f;
    } else if (c >= 0xf0 && c <= 0xf4) {
      count = 3;
      min = 0x10000;
      value = c & 7;
    } else
      return false;
    if (i + count > length)
      return false;
    while (count--) {
      unsigned next = s[i++];
      if ((next & 0xc0) != 0x80)
        return false;
      value = (value << 6) | (next & 0x3f);
    }
    if (value < min || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff))
      return false;
  }
  return true;
}
static void process(char *line, size_t length) {
  if (!valid_utf8((const unsigned char *)line, length))
    return;
  const char *end = NULL;
  cJSON *cmd = cJSON_ParseWithOpts(line, &end, true);
  if (!cmd || !valid_envelope(cmd)) {
    cJSON_Delete(cmd);
    return;
  }
  const char *name = str(cmd, "name"), *client = str(cmd, "client_id");
  uint32_t seq =
      (uint32_t)cJSON_GetNumberValue(cJSON_GetObjectItem(cmd, "command_seq"));
  uint8_t fingerprint[32];
  size_t hash_length = 0;
  if (psa_hash_compute(PSA_ALG_SHA_256, (const uint8_t *)line, length,
                       fingerprint, sizeof(fingerprint),
                       &hash_length) != PSA_SUCCESS) {
    cJSON_Delete(cmd);
    return;
  }
  bool read = equal(name, "hello") || equal(name, "status.get");
  bool owned_at_entry = equal(client, owner);
  cJSON *result = NULL;
  const char *code = NULL, *message = NULL;
  if (!equal(name, "hello") && !equal(str(cmd, "target_boot_id"), boot_id)) {
    code = "STALE_BOOT";
    message = "Node boot changed; reconnect";
  } else {
    for (int i = 0; i < CACHE_COUNT; i++)
      if ((cache[i].seq == seq ||
           equal(cache[i].command, str(cmd, "command_id"))) &&
          equal(client, cache[i].client)) {
        if (memcmp(cache[i].hash, fingerprint, 32) == 0) {
          send_text(cache[i].reply);
          cJSON_Delete(cmd);
          return;
        }
        code = "COMMAND_CONFLICT";
        message = "Sequence reused with changed contents";
        break;
      }
    if (!code && !equal(name, "hello") && !equal(name, "control.claim") &&
        !equal(client, owner)) {
      code = "NOT_OWNER";
      message = "Claim the node first";
    }
    if (!code && equal(client, owner) && seq <= high_sequence &&
        !equal(name, "hello")) {
      code = "COMMAND_EXPIRED";
      message = "Older command will not be executed";
    }
  }
  cJSON *args = cJSON_GetObjectItem(cmd, "args");
  bool supported = equal(name, "hello") || equal(name, "control.claim") ||
                   equal(name, "control.keepalive") ||
                   equal(name, "control.release") || equal(name, "status.get");
  if (!code && !supported) {
    const char *unavailable[] = {
        "session.open",   "session.close",   "config.set",      "run.prepare",
        "run.arm",        "run.start",       "run.stop",        "run.summary",
        "artifact.begin", "artifact.put",    "artifact.commit", "artifact.list",
        "artifact.get",   "artifact.delete", "audio.capture",   "audio.encode",
        "audio.decode",   "audio.play",      "operation.stop",  "diag.run",
        "fault.set",      "fault.fire",      "clock.arm",       "clock.emit",
        "clock.install",  "clock.stop"};
    code = "UNSUPPORTED_COMMAND";
    for (unsigned i = 0; i < sizeof(unavailable) / sizeof(unavailable[0]); i++)
      if (equal(name, unavailable[i]))
        code = "MISSING_CAPABILITY";
    message = "Diagnostic firmware supports identity and health only";
  }
  if (!code && !equal(name, "control.claim") && cJSON_GetArraySize(args) != 0) {
    code = "INVALID_ARGUMENT";
    message = "This diagnostic command accepts no arguments";
  }
  if (!code) {
    if (equal(name, "hello"))
      result = hello();
    else if (equal(name, "control.claim")) {
      const char *requested = str(args, "node_role");
      if (cJSON_GetArraySize(args) != 1 ||
          (!equal(requested, "A") && !equal(requested, "B"))) {
        code = "INVALID_ARGUMENT";
        message = "node_role must be A or B";
      } else if (owner[0] && !equal(owner, client)) {
        code = "BUSY";
        message = "Another host owns this node";
      } else {
        if (!equal(owner, client)) {
          memset(cache, 0, sizeof(cache));
          high_sequence = 0;
        }
        snprintf(owner, sizeof(owner), "%s", client);
        snprintf(role, sizeof(role), "%s", requested);
        lease_until = esp_timer_get_time() + 5000000;
        result = cJSON_CreateObject();
        add_n(result, "lease_expires_us", lease_until);
        add_s(result, "state", "idle");
      }
    } else if (equal(name, "control.keepalive")) {
      lease_until = esp_timer_get_time() + 5000000;
      result = cJSON_CreateObject();
      add_n(result, "lease_expires_us", lease_until);
    } else if (equal(name, "control.release")) {
      owner[0] = role[0] = 0;
      lease_until = 0;
      result = cJSON_CreateObject();
      add_s(result, "state", "idle");
    } else if (equal(name, "status.get"))
      result = health();
    else {
      code = "MISSING_CAPABILITY";
      message = "Diagnostic firmware supports identity and health only";
    }
  }
  if (equal(client, owner) && seq > high_sequence)
    high_sequence = seq;
  char *encoded = reply(cmd, result, code, message);
  if (encoded) {
    if (!read && (owned_at_entry || equal(client, owner)) &&
        !equal(code, "COMMAND_CONFLICT") && !equal(code, "COMMAND_EXPIRED") &&
        strlen(encoded) < sizeof(cache[0].reply)) {
      cached_reply *c = &cache[cache_next++ % CACHE_COUNT];
      c->seq = seq;
      snprintf(c->client, sizeof(c->client), "%s", client);
      snprintf(c->command, sizeof(c->command), "%s", str(cmd, "command_id"));
      memcpy(c->hash, fingerprint, 32);
      strcpy(c->reply, encoded);
    }
    send_text(encoded);
    free(encoded);
  }
  cJSON_Delete(cmd);
}
static void emit_health(void) {
  cJSON *o = cJSON_CreateObject();
  add_n(o, "v", 2);
  add_s(o, "kind", "event");
  add_s(o, "device_id", device_id);
  add_s(o, "boot_id", boot_id);
  add_s(o, "node_role", role[0] ? role : NULL);
  add_n(o, "event_seq", ++event_sequence);
  add_n(o, "uptime_us", esp_timer_get_time());
  add_s(o, "run_id", NULL);
  add_s(o, "name", "health");
  cJSON_AddItemToObject(o, "data", health());
  char *text = cJSON_PrintUnformatted(o);
  if (!text || !send_text(text))
    telemetry_drops++;
  free(text);
  cJSON_Delete(o);
}
static void alloc_failed(size_t size, uint32_t caps, const char *function) {
  allocation_failures++;
}
void app_main(void) {
  ESP_ERROR_CHECK(psa_crypto_init() == PSA_SUCCESS ? ESP_OK : ESP_FAIL);
  ESP_ERROR_CHECK(heap_caps_register_failed_alloc_callback(alloc_failed));
  ESP_ERROR_CHECK(nvs_flash_init());
  uint8_t mac[6];
  ESP_ERROR_CHECK(esp_efuse_mac_get_default(mac));
  snprintf(device_id, sizeof(device_id), "esp-%02x%02x%02x%02x%02x%02x", mac[0],
           mac[1], mac[2], mac[3], mac[4], mac[5]);
  nvs_handle_t nvs;
  ESP_ERROR_CHECK(nvs_open("lora_diag", NVS_READWRITE, &nvs));
  uint32_t count = 0;
  esp_err_t err = nvs_get_u32(nvs, "boot_count", &count);
  ESP_ERROR_CHECK(err == ESP_ERR_NVS_NOT_FOUND ? ESP_OK : err);
  ESP_ERROR_CHECK(count == UINT32_MAX ? ESP_ERR_INVALID_STATE : ESP_OK);
  ESP_ERROR_CHECK(nvs_set_u32(nvs, "boot_count", ++count));
  ESP_ERROR_CHECK(nvs_commit(nvs));
  nvs_close(nvs);
  snprintf(boot_id, sizeof(boot_id), "%s:%" PRIu32, device_id, count);
  usb_serial_jtag_driver_config_t config = {.tx_buffer_size = 4096,
                                            .rx_buffer_size = 4096};
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
  char *line = malloc(MAX_RECORD);
  ESP_ERROR_CHECK(line ? ESP_OK : ESP_ERR_NO_MEM);
  size_t used = 0;
  bool discard = false;
  int64_t next_health = esp_timer_get_time() + 1000000;
  while (true) {
    uint8_t chunk[256];
    int n = usb_serial_jtag_read_bytes(chunk, sizeof(chunk), pdMS_TO_TICKS(20));
    for (int i = 0; i < n; i++) {
      if (chunk[i] == '\n') {
        if (!discard && used) {
          if (line[used - 1] == '\r')
            used--;
          line[used] = 0;
          process(line, used);
        }
        used = 0;
        discard = false;
      } else if (!discard) {
        line[used++] = (char)chunk[i];
        if (used >= MAX_RECORD) {
          discard = true;
          used = 0;
        }
      }
    }
    int64_t now = esp_timer_get_time();
    if (owner[0] && now > lease_until) {
      owner[0] = role[0] = 0;
      memset(cache, 0, sizeof(cache));
      high_sequence = 0;
    }
    if (now >= next_health) {
      emit_health();
      next_health = now + 1000000;
    }
  }
}
