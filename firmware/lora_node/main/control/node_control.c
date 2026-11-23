#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "codec2_dependency.h"

#include "node_control.h"
#include "radio/radio_config_json.h"
#include "radio/rf_execution.h"
#include "generated/execution_profile.h"
#include "generated/audio_profile.h"
#include "generated/radio_board.h"
#include "artifacts/artifact_store.h"
#include "protocol/strict_json.h"
#include "protocol/secure_json.h"
#include "protocol/chunk_bytes.h"
#include "security/crypto_benchmark.h"
#include "generated/crypto_benchmark_profile.h"

typedef struct {
    uint32_t sequence;
    uint8_t hash[32];
    char client[37], command[37], reply[1024];
    bool valid, key_setup;
} cached_reply;

typedef struct {
    char client[37];
    uint32_t sequence;
} client_watermark;
typedef struct {
    size_t length;
    char bytes[NODE_RECORD_BYTES];
} record;
typedef struct {
    record slots[NODE_EVENT_SLOTS];
    unsigned head, count, capacity;
} record_queue;

typedef struct {
    bool active, verifying, audio, capture, benchmark;
    crypto_benchmark *crypto;
    crypto_benchmark_status crypto_status;
    char artifact_id[37];
    node_audio_progress audio_progress;
    char id[37], run_id[37];
    uint8_t *buffer;
    uint32_t iterations, completed, bytes, offset;
    int64_t started, deadline;
} operation;

struct node_control {
    node_platform port;
    codec2_frame_format codec2_format;
    bool codec2_library_ready;
    artifact_store *artifacts;
    char owner[37], role[2];
    int64_t lease_until, next_health, next_diagnostic;
    bool linked, oom, discard, dispatching;
    size_t used;
    char line[NODE_RECORD_BYTES], encoded[NODE_RECORD_BYTES];
    record_queue replies, events;
    cached_reply cache[NODE_CACHE_SLOTS];
    unsigned cache_next;
    client_watermark clients[16]; // Never evict a sequence fence within a boot.
    operation op;
    rf_execution rf;
    node_link_settings link;
    uint32_t config_revision;
    char config_failure[1024], mutation_success[1024];
    char last_operation[37];
    uint64_t event_sequence, telemetry_drops, reply_drops;
    uint64_t rx_records, oversized, rejected_json, rejected_envelope, backpressure;
    uint64_t diagnostics_pending, link_losses, completed_operations;
    char error_code[40], error_message[161];
};

static int64_t now(node_control *n) { return n->port.now_us(n->port.context); }
static bool eq(const char *a, const char *b) { return a && b && !strcmp(a, b); }
static void wipe_bytes(void *bytes, size_t length)
{
    volatile uint8_t *p = bytes;
    while (length--) *p++ = 0;
}
static void retire_key_cache(node_control *n)
{
    if (rf_execution_security_ready(&n->rf)) return;
    for (unsigned i = 0; i < NODE_CACHE_SLOTS; i++)
        if (n->cache[i].key_setup) wipe_bytes(&n->cache[i], sizeof(n->cache[i]));
}
static const cJSON *item(const cJSON *o, const char *key)
{
    return cJSON_GetObjectItemCaseSensitive(o, key);
}
static const char *text(const cJSON *o, const char *key)
{
    return cJSON_GetStringValue(item(o, key));
}
static cJSON *object(node_control *n)
{
    cJSON *o = cJSON_CreateObject();
    if (!o)
        n->oom = true;
    return o;
}
static void add(node_control *n, cJSON *o, const char *key, cJSON *v)
{
    if (!o || !v || !cJSON_AddItemToObject(o, key, v)) {
        cJSON_Delete(v);
        n->oom = true;
    }
}
static void string(node_control *n, cJSON *o, const char *key, const char *v)
{
    add(n, o, key, v ? cJSON_CreateString(v) : cJSON_CreateNull());
}
static void number(node_control *n, cJSON *o, const char *key, double v)
{
    add(n, o, key, cJSON_CreateNumber(v));
}
static void boolean(node_control *n, cJSON *o, const char *key, bool v)
{
    add(n, o, key, cJSON_CreateBool(v));
}

static bool uuid(const char *s)
{
    if (!s || strlen(s) != 36)
        return false;
    for (unsigned i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (s[i] != '-')
                return false;
        } else if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f')))
            return false;
    }
    return true;
}
static bool boot_identifier(const char *s)
{
    if (!s || strlen(s) < 18 || strlen(s) > 27 || strncmp(s, "esp-", 4) || s[16] != ':' ||
        s[17] < '1' || s[17] > '9')
        return false;
    for (unsigned i = 4; i < 16; i++)
        if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f')))
            return false;
    uint64_t count = 0;
    for (unsigned i = 17; s[i]; i++) {
        if (s[i] < '0' || s[i] > '9')
            return false;
        count = count * 10 + (unsigned)(s[i] - '0');
    }
    return count <= UINT32_MAX;
}
static bool uint32_value(const cJSON *v, uint32_t minimum, uint32_t maximum)
{
    return strict_json_integer(v) && isfinite(v->valuedouble) && v->valuedouble >= minimum &&
           v->valuedouble <= maximum && floor(v->valuedouble) == v->valuedouble;
}
static bool exact_keys(const cJSON *o, const char *const *keys, size_t count)
{
    if (!cJSON_IsObject(o) || cJSON_GetArraySize(o) != (int)count)
        return false;
    for (size_t i = 0; i < count; i++)
        if (!item(o, keys[i]))
            return false;
    return true;
}
static const char *envelope_error(const cJSON *o)
{
    static const char *const keys[] = {"v",         "kind",        "command_id",
                                       "client_id", "command_seq", "target_boot_id",
                                       "run_id",    "name",        "args"};
    if (!exact_keys(o, keys, 9))
        return "envelope";
    if (!uint32_value(item(o, "v"), 0, UINT32_MAX))
        return "v";
    if (!eq(text(o, "kind"), "command"))
        return "kind";
    if (!uuid(text(o, "command_id")))
        return "command_id";
    if (!uuid(text(o, "client_id")))
        return "client_id";
    if (!uint32_value(item(o, "command_seq"), 1, UINT32_MAX))
        return "command_seq";
    if (!cJSON_IsNull(item(o, "target_boot_id")) && !boot_identifier(text(o, "target_boot_id")))
        return "target_boot_id";
    if (!cJSON_IsNull(item(o, "run_id")) && !uuid(text(o, "run_id")))
        return "run_id";
    const char *name = text(o, "name");
    if (!name || !name[0] || strlen(name) > 64)
        return "name";
    if (!cJSON_IsObject(item(o, "args")))
        return "args";
    return NULL;
}

static bool enqueue(record_queue *q, const char *wire)
{
    size_t length = strlen(wire);
    if (q->count == q->capacity || length + 1 > NODE_RECORD_BYTES)
        return false;
    record *r = &q->slots[(q->head + q->count) % q->capacity];
    memcpy(r->bytes, wire, length);
    r->bytes[length++] = '\n';
    r->length = length;
    q->count++;
    return true;
}
static void send_reply(node_control *n, const char *wire)
{
    if (!enqueue(&n->replies, wire))
        n->reply_drops++;
}
static bool encode(node_control *n, cJSON *o)
{
    bool ok = o && !n->oom && cJSON_PrintPreallocated(o, n->encoded, sizeof(n->encoded) - 1, false);
    cJSON_Delete(o);
    return ok;
}
static cJSON *error(node_control *n, const char *code, const char *message, const char *field)
{
    if (!code)
        return cJSON_CreateNull();
    cJSON *o = object(n);
    string(n, o, "code", code);
    string(n, o, "message", message);
    string(n, o, "field", field);
    boolean(n, o, "retryable", false);
    return o;
}
static cJSON *command_reply(node_control *n, const cJSON *cmd, uint32_t sequence,
                            cJSON *result, const char *code, const char *message, const char *field)
{
    cJSON *reply = object(n);
    number(n, reply, "v", 2); string(n, reply, "kind", "reply");
    string(n, reply, "command_id", text(cmd,"command_id")); number(n, reply,"command_seq",sequence);
    string(n, reply,"device_id",n->port.device_id); string(n,reply,"boot_id",n->port.boot_id);
    number(n,reply,"uptime_us",now(n)); boolean(n,reply,"ok",code == NULL);
    add(n,reply,"result",result ? result : cJSON_CreateNull());
    add(n,reply,"error",error(n,code,message,field));
    return reply;
}
static cJSON *capabilities(node_control *n)
{
    cJSON *o = object(n), *limits = object(n);
    static const char *const disabled[] = {
        "codec2_3200",
        "echo",           "clock_sync",  "fault_injection"};
    for (size_t i = 0; i < sizeof(disabled) / sizeof(disabled[0]); i++)
        boolean(n, o, disabled[i], false);
    boolean(n, o, "security_gcm", n->port.radio && n->port.radio->available);
    boolean(n, o, "radio", n->port.radio && n->port.radio->available);
    boolean(n, o, "fragmentation", n->port.radio && n->port.radio->available);
    boolean(n, o, "ack_retry", n->port.radio && n->port.radio->available);
    boolean(n, o, "audio_capture", n->port.audio.capture);
    boolean(n, o, "audio_playback", n->port.audio.playback);
    boolean(n, o, "memory_stats", true);
    cJSON *radio = object(n);
    if (n->port.radio) {
        const char *variant = n->port.radio->variant == RADIO_HELTEC_V42_GC1109 ? "heltec_v4_2_gc1109" :
            n->port.radio->variant == RADIO_HELTEC_V43_KCT8103L ? "heltec_v4_3_kct8103l" : "unselected";
        string(n, radio, "selected_board_variant", variant);
        string(n, radio, "board_reference_sha256", RADIO_BOARD_REFERENCE_SHA256);
        string(n, radio, "initialization_error", n->port.radio->error);
        boolean(n, radio, "physical_qualified", false);
    }
    add(n, o, "radio_limits", radio);
    number(n, limits, "max_record_bytes", NODE_RECORD_BYTES);
    number(n, limits, "reply_queue_records", NODE_REPLY_SLOTS);
    number(n, limits, "telemetry_queue_records", NODE_EVENT_SLOTS);
    number(n, limits, "duplicate_cache_records", NODE_CACHE_SLOTS);
    number(n, limits, "max_clients_per_boot", 16);
    number(n, limits, "diag_max_iterations", 10000);
    number(n, limits, "diag_max_payload_bytes", NODE_PROBE_BYTES);
    number(n, limits, "operation_timeout_us", NODE_OPERATION_US);
    number(n, limits, "operation_slice_bytes", 512);
    cJSON *kinds = cJSON_CreateStringArray((const char *[]){"memory_probe", "crypto_benchmark"}, 2);
    add(n, limits, "diag_kinds", kinds);
    cJSON *benchmark = object(n);
    string(n, benchmark, "profile", CRYPTO_BENCH_PROFILE);
    string(n, benchmark, "schema_sha256", CRYPTO_BENCH_SCHEMA_SHA256);
    string(n, benchmark, "vector_sha256", CRYPTO_BENCH_VECTOR_SHA256);
    number(n, benchmark, "max_iterations", CRYPTO_BENCH_MAX_ITERATIONS);
    number(n, benchmark, "warmup_operations", CRYPTO_BENCH_WARMUPS);
    number(n, benchmark, "page_samples", CRYPTO_BENCH_PAGE);
    add(n, limits, "crypto_benchmark", benchmark);
    cJSON *codec = object(n);
    string(n, codec, "version", codec2_dependency_version());
    string(n, codec, "source_commit", codec2_dependency_revision());
    boolean(n, codec, "library_ready", n->codec2_library_ready);
    number(n, codec, "mode", n->codec2_library_ready ? 3200 : 0);
    number(n, codec, "samples_per_frame", n->codec2_format.samples);
    number(n, codec, "bits_per_frame", n->codec2_format.bits);
    number(n, codec, "bytes_per_frame", n->codec2_format.bytes);
    number(n, codec, "sample_rate_hz", n->codec2_format.sample_rate_hz);
    string(n, codec, "build_options", "mode3200_only;kiss_fft;float;O2;no_fast_math");
    add(n, limits, "codec2_library", codec);
    cJSON *files = object(n);
    string(n, files, "profile", ARTIFACT_PROFILE);
    string(n, files, "schema_sha256", ARTIFACT_SCHEMA_SHA256);
    add(n, files, "commands", cJSON_CreateStringArray(
        (const char *[]){"artifact.begin", "artifact.list", "artifact.delete", "artifact.put", "artifact.commit", "artifact.get"}, 6));
    number(n, files, "max_artifact_bytes", ARTIFACT_MAX_BYTES);
    number(n, files, "node_total_artifact_bytes", ARTIFACT_TOTAL_BYTES);
    number(n, files, "node_artifact_slots", ARTIFACT_SLOTS);
    number(n, files, "artifact_chunk_bytes", ARTIFACT_CHUNK_BYTES);
    add(n, limits, "artifact_transfer", files);
    if (n->port.radio) {
        cJSON *execution = object(n);
        string(n, execution, "profile", EXECUTION_PROFILE);
        string(n, execution, "schema_sha256", EXECUTION_SCHEMA_SHA256);
        add(n, execution, "commands", cJSON_CreateStringArray((const char *[]){"config.set","session.open","session.close","run.prepare","run.arm","run.start","run.stop","run.summary"},8));
        add(n, limits, "execution", execution);
        cJSON *execution_limits=object(n);
        number(n,execution_limits,"max_message_bytes",65536);number(n,execution_limits,"max_messages_per_run",1);
        number(n,execution_limits,"max_fragments_per_message",4096);number(n,execution_limits,"max_duration_ms",3600000);
        number(n,execution_limits,"max_retries",2);
        string(n,execution_limits,"irq_timestamp_phase","task_observed_dio1");
        add(n,limits,"execution_limits",execution_limits);
    }
    if (n->port.audio.playback || n->port.audio.capture) {
        cJSON *audio = object(n);
        string(n, audio, "profile", AUDIO_PROFILE);
        string(n, audio, "schema_sha256", AUDIO_SCHEMA_SHA256);
        const char *commands[2]; unsigned count = 0;
        if (n->port.audio.playback) commands[count++] = "audio.play";
        if (n->port.audio.capture) commands[count++] = "audio.capture";
        add(n, audio, "commands", cJSON_CreateStringArray(commands, count));
        string(n, audio, "format", "pcm_s16le_8000_mono");
        number(n, audio, "sample_rate_hz", AUDIO_SAMPLE_RATE);
        number(n, audio, "max_samples", AUDIO_MAX_SAMPLES);
        number(n, audio, "output_gain_numerator", 1);
        number(n, audio, "output_gain_denominator", 8);
        number(n, audio, "hardware_gain_db", 6);
        int pins[] = {AUDIO_OUTPUT_BCLK, AUDIO_OUTPUT_WS, AUDIO_OUTPUT_DIN};
        add(n, audio, "output_gpio", cJSON_CreateIntArray(pins, 3));
        int input_pins[] = {AUDIO_INPUT_BCLK, AUDIO_INPUT_WS, AUDIO_INPUT_SD};
        add(n, audio, "input_gpio", cJSON_CreateIntArray(input_pins, 3));
        string(n, audio, "input_slot", "left_24_msb_in_32");
        string(n, audio, "input_conversion", "signed_high_16_bits_no_gain");
        number(n, audio, "warmup_samples", AUDIO_WARMUP_SAMPLES);
        string(n, audio, "underflow_detection", "dma_callback_lateness");
        add(n, limits, "audio_io", audio);
    }
    add(n, o, "resource_limits", limits);
    number(n, o, "timestamp_resolution_us", 1);
    return o;
}
static cJSON *heap(node_control *n, const node_heap *h)
{
    if (!h->present)
        return cJSON_CreateNull();
    cJSON *o = object(n);
    number(n, o, "free_bytes", h->free_bytes);
    number(n, o, "minimum_free_bytes", h->minimum_free_bytes);
    number(n, o, "largest_free_bytes", h->largest_free_bytes);
    return o;
}
static size_t queued_bytes(const record_queue *q)
{
    size_t bytes = 0;
    for (unsigned i = 0; i < q->count; i++)
        bytes += q->slots[(q->head + i) % q->capacity].length;
    return bytes;
}
static cJSON *health(node_control *n)
{
    node_heap internal = {0}, psram = {0};
    uint32_t failures = 0;
    n->port.memory(n->port.context, &internal, &psram, &failures);
    cJSON *o = object(n), *memory = object(n), *buffers = object(n), *traffic = object(n);
    string(n, o, "node_role", n->role[0] ? n->role : NULL);
    string(n, o, "state", n->op.active ? "running" : rf_execution_state(&n->rf));
    string(n, o, "run_id", n->op.active && n->op.run_id[0] ? n->op.run_id : rf_execution_busy(&n->rf)?n->rf.plan.run:NULL);
    string(n, o, "operation_id", n->op.active ? n->op.id : (n->rf.phase==RF_PREPARING||n->rf.phase==RF_RUNNING)?n->rf.plan.operation:NULL);
    number(n, o, "uptime_us", now(n));
    string(n, o, "reset_cause", n->port.reset_cause);
    bool configured = n->port.radio && n->port.radio->available && n->port.radio->configured;
    add(n, o, "radio", configured ? radio_config_radio(&n->port.radio->applied, n->port.radio->ldro_enabled) : cJSON_CreateNull());
    add(n, o, "link", configured ? radio_config_link(&n->link) : cJSON_CreateNull());
    number(n, o, "config_revision", n->config_revision);
    add(n, o, "capability_availability", capabilities(n));
    add(n, memory, "internal", heap(n, &internal));
    add(n, memory, "psram", heap(n, &psram));
    number(n, buffers, "serial_rx", n->used);
    number(n, buffers, "serial_tx_queued", queued_bytes(&n->replies) + queued_bytes(&n->events));
    number(n, buffers, "diagnostic", n->op.active && n->op.benchmark ? crypto_benchmark_bytes() : n->op.active && !n->op.audio ? n->op.bytes : 0);
    number(n, buffers, "artifacts_reserved", artifact_store_reserved_bytes(n->artifacts));
    add(n, memory, "buffers", buffers);
    number(n, memory, "allocation_failures", failures);
    add(n, o, "memory", memory);
    number(n, traffic, "rx_records", n->rx_records);
    number(n, traffic, "rx_oversized", n->oversized);
    number(n, traffic, "rx_json_rejected", n->rejected_json);
    number(n, traffic, "rx_envelope_rejected", n->rejected_envelope);
    number(n, traffic, "rx_backpressure", n->backpressure);
    number(n, traffic, "reply_drops", n->reply_drops);
    number(n, traffic, "link_losses", n->link_losses);
    number(n, traffic, "completed_operations", n->completed_operations);
    number(n, traffic, "operation_iterations", n->op.active ? n->op.completed : 0);
    add(n, o, "traffic", traffic);
    boolean(n, o, "security_ready", rf_execution_security_ready(&n->rf));
    string(n, o, "audio_state", n->op.active && n->op.audio ? (n->op.capture ? "capturing" : "playing") : (n->port.audio.playback || n->port.audio.capture) ? "idle" : "not_supported");
    number(n, o, "telemetry_drops", n->telemetry_drops);
    add(n, o, "last_error",
        error(n, n->error_code[0] ? n->error_code : NULL, n->error_message, NULL));
    string(n, o, "last_rx", NULL);
    return o;
}
static cJSON *hello(node_control *n)
{
    cJSON *o = object(n);
    string(n, o, "device_id", n->port.device_id);
    string(n, o, "boot_id", n->port.boot_id);
    string(n, o, "board_model", "Heltec WiFi LoRa 32 V4");
    string(n, o, "board_revision", NULL); // Printed revision still needs observation.
    string(n, o, "chip_model", "ESP32-S3");
    string(n, o, "firmware_version", n->port.firmware_version);
    string(n, o, "firmware_commit", NULL);
    string(n, o, "firmware_build_id", n->port.firmware_build_id);
    string(n, o, "idf_version", n->port.idf_version);
    string(n, o, "board_manifest_hash", n->port.board_manifest_hash);
    string(n, o, "provenance", "hardware");
    cJSON *versions = cJSON_CreateIntArray((int[]){2}, 1);
    add(n, o, "supported_wire_versions", versions);
    string(n, o, "contract_version", "2.0.0");
    string(n, o, "schema_sha256", n->port.schema_sha256);
    add(n, o, "capabilities", capabilities(n));
    boolean(n, o, "claimed", n->owner[0] != 0);
    string(n, o, "state", n->op.active ? "running" : rf_execution_state(&n->rf));
    return o;
}
static bool emit(node_control *n, const char *name, cJSON *data, const char *run_id)
{
    uint64_t sequence = ++n->event_sequence;
    cJSON *o = object(n);
    number(n, o, "v", 2);
    string(n, o, "kind", "event");
    string(n, o, "device_id", n->port.device_id);
    string(n, o, "boot_id", n->port.boot_id);
    string(n, o, "node_role", n->role[0] ? n->role : NULL);
    number(n, o, "event_seq", sequence);
    number(n, o, "uptime_us", now(n));
    string(n, o, "run_id", run_id);
    string(n, o, "name", name);
    add(n, o, "data", data);
    if (!encode(n, o) || !enqueue(&n->events, n->encoded)) { n->telemetry_drops++; return false; }
    return true;
}
static void remember_error(node_control *n, const char *code, const char *message)
{
    snprintf(n->error_code, sizeof(n->error_code), "%s", code);
    snprintf(n->error_message, sizeof(n->error_message), "%s", message);
}
static const char *const benchmark_paths[] = {"encrypt", "decrypt", "invalid_tag", "copy"};
static const char *const benchmark_phases[] = {"first_call", "warmup", "timed"};
static bool benchmark_page(node_control *n)
{
    const crypto_benchmark_page *page = crypto_benchmark_pending(n->op.crypto);
    if (!page) return true;
    cJSON *data = object(n), *samples = cJSON_CreateArray();
    string(n, data, "operation_id", n->op.id);
    string(n, data, "path", benchmark_paths[page->path]);
    string(n, data, "phase", benchmark_phases[page->phase]);
    number(n, data, "first_index", page->first_index);
    number(n, data, "page_index", crypto_benchmark_progress(n->op.crypto).pages_emitted);
    number(n, data, "payload_bytes", n->op.bytes);
    for (unsigned i = 0; i < page->count; i++) {
        cJSON *sample = cJSON_CreateArray();
        if (!sample || !cJSON_AddItemToArray(sample, cJSON_CreateNumber(page->samples[i].start_us)) ||
            !cJSON_AddItemToArray(sample, cJSON_CreateNumber(page->samples[i].end_us)) ||
            !cJSON_AddItemToArray(sample, cJSON_CreateBool(page->samples[i].checked)) ||
            !cJSON_AddItemToArray(samples, sample)) { cJSON_Delete(sample); n->oom = true; break; }
    }
    add(n, data, "samples", samples);
    if (!emit(n, "crypto.benchmark", data, n->op.run_id[0] ? n->op.run_id : NULL)) return false;
    crypto_benchmark_ack(n->op.crypto);
    return true;
}
static void benchmark_result(node_control *n, cJSON *result)
{
    operation *op = &n->op;
    string(n, result, "kind", "crypto_benchmark");
    string(n, result, "profile", CRYPTO_BENCH_PROFILE);
    string(n, result, "schema_sha256", CRYPTO_BENCH_SCHEMA_SHA256);
    string(n, result, "vector_sha256", CRYPTO_BENCH_VECTOR_SHA256);
    number(n, result, "payload_bytes", op->bytes);
    number(n, result, "iterations_requested", op->iterations);
    number(n, result, "pages_emitted", op->crypto_status.pages_emitted);
    number(n, result, "samples_lost", op->crypto_status.samples_lost);
    boolean(n, result, "checked_complete", op->crypto_status.finished && !op->crypto_status.failed && !op->crypto_status.samples_lost);
    cJSON *counts = object(n);
    for (unsigned path = 0; path < 4; path++) {
        cJSON *phases = object(n);
        for (unsigned phase = 0; phase < 3; phase++)
            number(n, phases, benchmark_phases[phase], op->crypto_status.checked[path][phase]);
        add(n, counts, benchmark_paths[path], phases);
    }
    add(n, result, "checked_counts", counts);
    string(n, result, "implementation", "PSA_GCM_MbedTLS_4.1.0_TFPSA_1.1.0");
    string(n, result, "timer", "platform_monotonic_us");
    number(n, result, "timestamp_resolution_us", 1);
    number(n, result, "configured_cpu_frequency_mhz", n->port.cpu_frequency_mhz);
    boolean(n, result, "dynamic_frequency_enabled", n->port.dynamic_frequency);
    boolean(n, result, "hardware_aes_configured", n->port.hardware_aes);
    string(n, result, "buffer_policy", "fixed_nonoverlap_215B_output_16_sample_page");
    string(n, result, "measurement", "one_shot_PSA_call_including_provider_internal_work");
    string(n, result, "first_call_scope", "first_per_path_in_this_batch_not_cold_boot");
    string(n, result, "copy_baseline", "memcpy_payload_plus_16_tag_bytes_no_authentication");
    boolean(n, result, "public_vector_material_only", true);
}
static cJSON *manifest(node_control *n, const artifact_manifest *m);
static void finish_operation(node_control *n, const char *status, const char *code,
                             const char *message)
{
    if (!n->op.active)
        return;
    operation *op = &n->op;
    char audio_error[161];
    if (op->benchmark) {
        unsigned lost = 0;
        const crypto_benchmark_page *page = crypto_benchmark_pending(op->crypto);
        if (page && !benchmark_page(n)) lost = page->count;
        op->crypto_status = crypto_benchmark_progress(op->crypto);
        op->crypto_status.samples_lost += lost;
        if (!crypto_benchmark_destroy(&op->crypto)) {
            op->crypto_status.failed = true;
            status = "failed"; code = "INTERNAL_ERROR"; message = "Benchmark key retirement failed";
        }
        if (code) op->crypto_status.failed = true;
    }
    if (op->audio) {
        n->port.audio.stop(n->port.context);
        n->port.audio.poll(n->port.context, &op->audio_progress);
        if (op->capture) {
            if (eq(status, "completed") && !code) {
                if (artifact_store_capture_finish(n->artifacts, op->artifact_id, op->audio_progress.samples,
                    n->port.sha256, n->port.context) != ARTIFACT_OK) {
                    status = "failed"; code = "INTERNAL_ERROR"; message = "Capture hash/commit failed";
                }
            }
            if (!eq(status, "completed") || code) artifact_store_delete(n->artifacts, op->artifact_id);
        } else artifact_store_release(n->artifacts, op->artifact_id);
        if (code) {
            snprintf(audio_error, sizeof(audio_error), "%.75s; samples=%" PRIu32 " DMA_frames=%" PRIu32 " underflows=%" PRIu32, message,
                op->audio_progress.samples, op->audio_progress.dma_frames, op->audio_progress.underflows);
            message = audio_error;
        }
    } else if (op->buffer) n->port.deallocate(n->port.context, op->buffer);
    op->buffer = NULL;
    op->active = false;
    snprintf(n->last_operation, sizeof(n->last_operation), "%s", op->id);
    if (eq(status, "completed"))
        n->completed_operations++;
    if (code)
        remember_error(n, code, message);
    n->oom = false;
    cJSON *data = object(n), *result = code && !op->benchmark ? cJSON_CreateNull() : object(n);
    if (!code || op->benchmark) {
        if (op->benchmark) benchmark_result(n, result);
        else if (op->audio) {
            string(n, result, "kind", op->capture ? "audio.capture" : "audio.play");
            string(n, result, "artifact_id", op->artifact_id);
            number(n, result, "sample_rate_hz", AUDIO_SAMPLE_RATE);
            number(n, result, "samples_requested", op->bytes / 2);
            number(n, result, "samples_completed", op->audio_progress.samples);
            number(n, result, "dma_frames", op->audio_progress.dma_frames);
            number(n, result, "underflows", op->audio_progress.underflows);
            boolean(n, result, "dma_completed", op->audio_progress.done);
            number(n, result, "output_gain_numerator", 1);
            number(n, result, "output_gain_denominator", 8);
            number(n, result, "software_gain_db", -18.06179974);
            number(n, result, "hardware_gain_db", 6);
            boolean(n, result, "heard_verified", false);
            if (op->capture) {
                number(n, result, "raw_left_nonzero_samples", op->audio_progress.raw_left_nonzero);
                number(n, result, "raw_right_nonzero_samples", op->audio_progress.raw_right_nonzero);
                number(n, result, "raw_left_or", op->audio_progress.raw_left_or);
                number(n, result, "raw_right_or", op->audio_progress.raw_right_or);
                number(n, result, "overflows", op->audio_progress.underflows);
                number(n, result, "input_gain_numerator", 1);
                number(n, result, "input_gain_denominator", 1);
                number(n, result, "warmup_samples", AUDIO_WARMUP_SAMPLES);
                string(n, result, "input_conversion", "signed_high_16_bits_no_gain");
                const artifact_manifest *m = artifact_store_find(n->artifacts, op->artifact_id);
                add(n, result, "artifact", m ? manifest(n, m) : cJSON_CreateNull());
            }
        } else {
        string(n, result, "kind", "memory_probe");
        number(n, result, "iterations_completed", op->completed);
        number(n, result, "payload_bytes", op->bytes);
        number(n, result, "verified_bytes", (uint64_t)op->completed * op->bytes);
        }
        number(n, result, "duration_us", now(n) - op->started);
        string(n, result, "stop_reason", message);
    }
    string(n, data, "operation_id", op->id);
    string(n, data, "status", status);
    add(n, data, "result", result);
    add(n, data, "error", error(n, code, message, NULL));
    emit(n, "operation.result", data, op->run_id[0] ? op->run_id : NULL);
}
static void lose_owner(node_control *n, const char *reason)
{
    finish_operation(n, "cancelled", NULL, reason);
    rf_execution_abort(&n->rf,"peer_failure",true);
    artifact_store_release_owner(n->artifacts, n->owner);
    n->owner[0] = n->role[0] = 0;
    n->lease_until = 0;
    if (!n->dispatching && n->used) {
        wipe_bytes(n->line, sizeof(n->line));
        n->used = 0;
        n->discard = true; // Discard the rest of this interrupted record through LF.
    }
    memset(n->cache, 0, sizeof(n->cache));
    n->cache_next = 0;
}
static client_watermark *watermark(node_control *n, const char *client, bool reserve)
{
    client_watermark *empty = NULL;
    for (unsigned i = 0; i < 16; i++) {
        if (eq(n->clients[i].client, client))
            return &n->clients[i];
        if (!n->clients[i].client[0] && !empty)
            empty = &n->clients[i];
    }
    return reserve ? empty : NULL;
}
static bool known_unavailable(const char *name)
{
    static const char *const commands[] = {
        "session.open",    "session.close", "config.set",    "run.prepare",     "run.arm",
        "run.start",       "run.stop",      "run.summary",
        "audio.capture",
        "audio.encode",    "audio.decode",  "audio.play",    "fault.set",       "fault.fire",
        "clock.arm",       "clock.emit",    "clock.install", "clock.stop"};
    for (size_t i = 0; i < sizeof(commands) / sizeof(commands[0]); i++)
        if (eq(name, commands[i]))
            return true;
    return false;
}

static bool artifact_command(const char *name)
{
    return eq(name, "artifact.begin") || eq(name, "artifact.list") || eq(name, "artifact.delete") ||
           eq(name, "artifact.put") || eq(name, "artifact.commit") || eq(name, "artifact.get");
}
static const char *artifact_error(artifact_status status)
{
    static const char *const codes[] = {NULL, "INVALID_ARGUMENT", "RESOURCE_LIMIT",
        "ALLOCATION_FAILED", "ARTIFACT_NOT_FOUND", "INVALID_STATE", "BUSY",
        "OFFSET_MISMATCH", "CHECKSUM_MISMATCH", "INTERNAL_ERROR"};
    return codes[status];
}
static cJSON *manifest(node_control *n, const artifact_manifest *m)
{
    cJSON *o = object(n);
    string(n, o, "artifact_id", m->artifact_id);
    string(n, o, "kind", m->kind);
    string(n, o, "format", m->format);
    string(n, o, "sha256", m->sha256);
    number(n, o, "length_bytes", m->length_bytes);
    number(n, o, "next_offset", m->next_offset);
    const char *const states[] = {"uploading", "failed", "committed"};
    string(n, o, "state", states[m->state]);
    boolean(n, o, "in_use", m->in_use);
    string(n, o, "codec", NULL);
    string(n, o, "frame_count", NULL);
    string(n, o, "source_artifact_id", NULL);
    if (eq(m->format, "pcm_s16le_8000_mono")) {
        number(n, o, "sample_rate_hz", 8000);
        number(n, o, "sample_count", m->length_bytes / 2);
    } else {
        string(n, o, "sample_rate_hz", NULL);
        string(n, o, "sample_count", NULL);
    }
    return o;
}
static cJSON *artifact_list(node_control *n)
{
    cJSON *o = object(n), *files = cJSON_CreateArray();
    if (!files)
        n->oom = true;
    for (unsigned i = 0; i < ARTIFACT_SLOTS; i++) {
        const artifact_manifest *m = artifact_store_at(n->artifacts, i);
        if (m) {
            cJSON *entry = manifest(n, m);
            if (!files || !entry || !cJSON_AddItemToArray(files, entry)) {
                cJSON_Delete(entry);
                n->oom = true;
            }
        }
    }
    add(n, o, "artifacts", files);
    return o;
}

enum action { RF_COMMAND, CONFIGURE, NONE, CLAIM, KEEPALIVE, RELEASE, PROBE, BENCHMARK, STOP, PLAY, CAPTURE, RESERVE_FILE, DELETE_FILE, PUT_FILE, COMMIT_FILE, GET_FILE };
static void process(node_control *n, size_t length)
{
    n->rx_records++;
    retire_key_cache(n);
    if (n->replies.count == n->replies.capacity) {
        n->backpressure++;
        n->diagnostics_pending++;
        return; // A retry can be processed after the writer drains.
    }
    cJSON *cmd = strict_json_object(n->line, length);
    if (!cmd) {
        n->rejected_json++;
        n->diagnostics_pending++;
        return;
    }
    const char *field = envelope_error(cmd), *code = NULL, *message = NULL;
    bool valid_envelope = field == NULL;
    bool correlated =
        uuid(text(cmd, "command_id")) && uint32_value(item(cmd, "command_seq"), 1, UINT32_MAX);
    if (field) {
        n->rejected_envelope++;
        if (!correlated) {
            n->diagnostics_pending++;
            cJSON_Delete(cmd);
            return;
        }
        code = "INVALID_ARGUMENT";
        message = "Invalid command envelope";
    }
    const char *name = text(cmd, "name"), *client = text(cmd, "client_id");
    uint32_t sequence = (uint32_t)item(cmd, "command_seq")->valuedouble;
    const cJSON *args = item(cmd, "args");
    bool read = eq(name, "hello") || eq(name, "status.get") || eq(name, "artifact.list") || eq(name, "artifact.get") || eq(name,"run.summary");
    bool owned = !field && eq(client, n->owner);
    uint8_t fingerprint[32] = {0};
    client_watermark *mark = !field ? watermark(n, client, false) : NULL;
    if (!code && item(cmd, "v")->valuedouble != 2) {
        code = "UNSUPPORTED_VERSION";
        field = "v";
        message = "Wire version 2 required";
    }
    if (!code && !eq(name, "hello") && !eq(text(cmd, "target_boot_id"), n->port.boot_id)) {
        code = "STALE_BOOT";
        field = "target_boot_id";
        message = "Reconnect after a node reset";
    }
    if (!code && !n->port.sha256(n->port.context, n->line, length, fingerprint)) {
        code = "INTERNAL_ERROR";
        message = "Command fingerprint failed";
    }
    if (!code) {
        for (unsigned i = 0; i < NODE_CACHE_SLOTS; i++) {
            cached_reply *c = &n->cache[i];
            if (!c->valid || !eq(c->client, client) ||
                (c->sequence != sequence && !eq(c->command, text(cmd, "command_id"))))
                continue;
            if (!memcmp(c->hash, fingerprint, 32)) {
                send_reply(n, c->reply);
                cJSON_Delete(cmd);
                return;
            }
            code = "COMMAND_CONFLICT";
            message = "Reused command ID or sequence changed";
            break;
        }
    }
    if (!code && !eq(name, "hello") && !eq(name, "control.claim") && !owned) {
        code = "NOT_OWNER";
        message = "Claim this node before issuing commands";
    }
    if (!code && !eq(name, "hello") && mark && sequence <= mark->sequence) {
        code = "COMMAND_EXPIRED";
        message = "Command sequence is older than the boot high-water mark";
    }
    if (!code && !eq(name, "diag.run") && !eq(name, "audio.play") && !eq(name, "audio.capture") && !artifact_command(name) && !rf_execution_command(name) &&
        !cJSON_IsNull(item(cmd, "run_id"))) {
        code = "INVALID_ARGUMENT";
        field = "run_id";
        message = "Control commands require null run_id";
    }
    enum action action = NONE;
    rf_plan radio_plan;
    cJSON *radio_result=NULL;
    node_radio_settings radio_settings;
    node_link_settings link_settings;
    uint8_t *probe = NULL;
    const void *play_bytes = NULL;
    size_t play_length = 0;
    bool play_acquired = false, capture_reserved = false;
    artifact_spec file_spec = {0};
    uint8_t chunk[ARTIFACT_CHUNK_BYTES];
    size_t chunk_length = 0, chunk_offset = 0;
    uint32_t chunk_crc = 0;
    bool chunk_eof = false;
    uint32_t iterations = 0, bytes = 0;
    int64_t lease = now(n) + 5000000;
    int64_t operation_deadline = now(n) + NODE_OPERATION_US;
    char operation_id[37] = {0};
    bool fresh_claim = false;
    n->oom = false;
    cJSON *result = NULL;
    if (!code) {
        if (rf_execution_command(name)) {
            if(n->op.active) {code="BUSY";message="Another operation is active";}
            else {
                uint8_t id[16];n->port.random_bytes(n->port.context,id,sizeof(id));id[6]=(id[6]&15)|64;id[8]=(id[8]&63)|128;
                snprintf(operation_id,sizeof(operation_id),"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",id[0],id[1],id[2],id[3],id[4],id[5],id[6],id[7],id[8],id[9],id[10],id[11],id[12],id[13],id[14],id[15]);
                code=rf_execution_check(&n->rf,name,args,text(cmd,"run_id"),n->owner,n->role,n->port.device_id,n->config_revision,&n->link,operation_id,&radio_plan,&radio_result);
                if(!code) {action=RF_COMMAND;if(!radio_result)n->oom=true;}
                else message="Radio command rejected for this session, state or limit";
            }
        } else if (eq(name, "config.set")) {
            if (!n->port.radio || !n->port.radio->available) { code="MISSING_CAPABILITY"; message="Radio is unavailable"; }
            else if (n->op.active || rf_execution_busy(&n->rf)) { code="BUSY"; message="Configuration requires idle"; }
            else if (n->config_revision == UINT32_MAX) { code="RESOURCE_LIMIT"; message="Configuration revision exhausted"; }
            else if (!radio_config_parse(args,&radio_settings,&link_settings)) { code="INVALID_ARGUMENT"; message="Unsupported radio or link configuration"; field="args"; }
            else action=CONFIGURE;
        } else if (eq(name, "control.claim")) {
            const char *const keys[] = {"node_role"};
            if (!exact_keys(args, keys, 1) ||
                (!eq(text(args, "node_role"), "A") && !eq(text(args, "node_role"), "B"))) {
                code = "INVALID_ARGUMENT";
                field = "args.node_role";
                message = "Choose node role A or B";
            } else if (n->owner[0] && !owned) {
                code = "BUSY";
                message = "Another client owns this node";
            } else if ((n->op.active || n->rf.plan.session) && !eq(text(args, "node_role"), n->role)) {
                code = "INVALID_STATE";
                message = "Role changes require an idle node";
            } else if (!(mark = watermark(n, client, true))) {
                code = "RESOURCE_LIMIT";
                message = "Client sequence table full; reset required";
            } else {
                action = CLAIM;
                fresh_claim = !n->owner[0];
            }
        } else if (artifact_command(name)) {
            const char *id = text(args, "artifact_id");
            if (n->op.active || rf_execution_busy(&n->rf)) {
                code = "BUSY";
                message = "File access requires an idle node";
            } else if (eq(name, "artifact.list")) {
                if (cJSON_GetArraySize(args)) {
                    code = "INVALID_ARGUMENT";
                    field = "args";
                    message = "Listing accepts no arguments";
                }
            } else if (eq(name, "artifact.get")) {
                const char *const keys[] = {"artifact_id", "offset", "length_bytes"};
                if (!exact_keys(args, keys, 3) || !uuid(id) ||
                    !uint32_value(item(args, "offset"), 0, ARTIFACT_MAX_BYTES) ||
                    !uint32_value(item(args, "length_bytes"), 1, ARTIFACT_CHUNK_BYTES)) {
                    code = "INVALID_ARGUMENT";
                    field = "args";
                    message = "Invalid bounded file read";
                } else {
                    chunk_offset = (size_t)item(args, "offset")->valuedouble;
                    code = artifact_error(artifact_store_get(n->artifacts, id, chunk_offset,
                        chunk, (size_t)item(args, "length_bytes")->valuedouble,
                        &chunk_length, &chunk_eof));
                    if (code) message = "Reads require a committed file and valid range";
                    else action = GET_FILE;
                }
            } else if (eq(name, "artifact.commit")) {
                const char *const keys[] = {"artifact_id"};
                if (!exact_keys(args, keys, 1) || !uuid(id)) {
                    code = "INVALID_ARGUMENT";
                    field = "args.artifact_id";
                    message = "A lowercase artifact UUID is required";
                } else {
                    code = artifact_error(artifact_store_prepare_commit(n->artifacts, id,
                                                         n->port.sha256, n->port.context));
                    if (!code || eq(code, "CHECKSUM_MISMATCH")) action = COMMIT_FILE;
                    if (code) message = "File commit requires complete bytes and matching SHA-256";
                }
            } else if (eq(name, "artifact.put")) {
                const char *const keys[] = {"artifact_id", "offset", "data_b64", "crc32"};
                const char *crc = text(args, "crc32");
                bool crc_valid = crc && strlen(crc) == 8;
                for (unsigned i = 0; crc_valid && i < 8; i++) {
                    char c = crc[i];
                    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) crc_valid = false;
                    else chunk_crc = (chunk_crc << 4) | (uint32_t)(c <= '9' ? c - '0' : c - 'a' + 10);
                }
                if (!exact_keys(args, keys, 4) || !uuid(id) || !crc_valid ||
                    !uint32_value(item(args, "offset"), 0, ARTIFACT_MAX_BYTES) ||
                    !chunk_base64_decode(text(args, "data_b64"), chunk, sizeof(chunk), &chunk_length)) {
                    code = "INVALID_ARGUMENT";
                    field = "args";
                    message = "Invalid chunk fields, encoding or size";
                } else {
                    chunk_offset = (size_t)item(args, "offset")->valuedouble;
                    code = artifact_error(artifact_store_check_put(n->artifacts, id, chunk_offset,
                                                                  chunk, chunk_length, chunk_crc));
                    if (code) message = "Chunk rejected; stored bytes and offset are unchanged";
                    else action = PUT_FILE;
                }
            } else if (eq(name, "artifact.begin")) {
                const char *const keys[] = {"artifact_id", "kind", "length_bytes", "sha256", "format"};
                if (!exact_keys(args, keys, 5) ||
                    !uint32_value(item(args, "length_bytes"), 1, UINT32_MAX)) {
                    code = "INVALID_ARGUMENT";
                    field = "args";
                    message = "Invalid file reservation arguments";
                } else {
                    file_spec = (artifact_spec){.artifact_id = id, .kind = text(args, "kind"),
                        .length_bytes = (size_t)item(args, "length_bytes")->valuedouble,
                        .sha256 = text(args, "sha256"), .format = text(args, "format")};
                    code = artifact_error(artifact_store_begin(n->artifacts, client, &file_spec));
                    if (code)
                        message = "File reservation failed; existing files are unchanged";
                    else
                        action = RESERVE_FILE;
                }
            } else {
                const char *const keys[] = {"artifact_id"};
                if (!exact_keys(args, keys, 1) || !uuid(id)) {
                    code = "INVALID_ARGUMENT";
                    field = "args.artifact_id";
                    message = "A lowercase artifact UUID is required";
                } else {
                    const artifact_manifest *m = artifact_store_find(n->artifacts, id);
                    if (!m) {
                        code = "ARTIFACT_NOT_FOUND";
                        message = "File does not exist in this boot";
                    } else if (m->in_use) {
                        code = "BUSY";
                        message = "Release the active file consumer before deletion";
                    } else
                        action = DELETE_FILE;
                }
            }
        } else if (eq(name, "audio.capture")) {
            const char *const keys[] = {"artifact_id", "sample_count"};
            if (!n->port.audio.capture) { code = "MISSING_CAPABILITY"; message = "Capture is not configured for this board"; }
            else if (!exact_keys(args, keys, 2) || !uuid(text(args, "artifact_id")) ||
                !uint32_value(item(args, "sample_count"), 1, AUDIO_MAX_SAMPLES)) {
                code = "INVALID_ARGUMENT"; message = "Capture requires a UUID and 1-24000 samples";
            } else if (n->op.active || rf_execution_busy(&n->rf)) { code = "BUSY"; message = "Another operation is active"; }
            else {
                void *destination = NULL;
                bytes = (uint32_t)item(args, "sample_count")->valuedouble * 2;
                code = artifact_error(artifact_store_capture_begin(n->artifacts, client, text(args, "artifact_id"), bytes / 2, &destination));
                if (code) message = "Capture reservation failed";
                else { action = CAPTURE; capture_reserved = true; play_bytes = destination; }
            }
        } else if (eq(name, "audio.play")) {
            const char *const keys[] = {"artifact_id"};
            const char *id = text(args, "artifact_id");
            const artifact_manifest *m = uuid(id) ? artifact_store_find(n->artifacts, id) : NULL;
            if (!n->port.audio.playback) { code = "MISSING_CAPABILITY"; message = "Playback is not configured for this board"; }
            else if (!exact_keys(args, keys, 1) || !uuid(id)) { code = "INVALID_ARGUMENT"; message = "A file UUID is required"; }
            else if (n->op.active || rf_execution_busy(&n->rf)) { code = "BUSY"; message = "Another operation is active"; }
            else if (!m) { code = "ARTIFACT_NOT_FOUND"; message = "File not found"; }
            else if (!eq(m->format, "pcm_s16le_8000_mono") || m->length_bytes % 2 || m->length_bytes > AUDIO_MAX_SAMPLES * 2) {
                code = "INVALID_ARGUMENT"; message = "Playback requires complete 8 kHz signed-16-bit mono PCM";
            } else {
                code = artifact_error(artifact_store_acquire(n->artifacts, id, &play_bytes, &play_length));
                if (code) message = "Playback requires an unused committed file";
                else { action = PLAY; play_acquired = true; bytes = play_length; }
            }
        } else if (eq(name, "diag.run")) {
            const char *const keys[] = {"kind", "iterations", "payload_bytes"};
            if (!exact_keys(args, keys, 3) || !text(args, "kind") ||
                !uint32_value(item(args, "iterations"), 1, 10000) ||
                !uint32_value(item(args, "payload_bytes"), 1, NODE_PROBE_BYTES)) {
                code = "INVALID_ARGUMENT";
                field = "args";
                message = "Invalid diagnostic kind or bounded workload";
            } else if (eq(text(args, "kind"), "crypto_benchmark")) {
                bytes = (uint32_t)item(args, "payload_bytes")->valuedouble;
                iterations = (uint32_t)item(args, "iterations")->valuedouble;
                if (bytes != 16 && bytes != 64 && bytes != 160 && bytes != 199) {
                    code = "INVALID_ARGUMENT"; message = "Benchmark payload must be 16, 64, 160 or 199 bytes";
                } else if (n->op.active || n->op.crypto || rf_execution_busy(&n->rf)) {
                    code = "BUSY"; message = "Another operation or cleanup is active";
                } else action = BENCHMARK;
            } else if (!eq(text(args, "kind"), "memory_probe")) {
                code = "MISSING_CAPABILITY";
                message = "Diagnostic kind is not implemented";
            } else if (n->op.active || rf_execution_busy(&n->rf)) {
                code = "BUSY";
                message = "Another operation is active";
            } else {
                iterations = (uint32_t)item(args, "iterations")->valuedouble;
                bytes = (uint32_t)item(args, "payload_bytes")->valuedouble;
                probe = n->port.allocate(n->port.context, bytes);
                if (!probe) {
                    code = "ALLOCATION_FAILED";
                    message = "Diagnostic buffer allocation failed";
                } else {
                    action = PROBE;
                }
            }
        } else if (eq(name, "operation.stop")) {
            const char *const keys[] = {"operation_id"};
            const char *id = text(args, "operation_id");
            if (!exact_keys(args, keys, 1) || !uuid(id)) {
                code = "INVALID_ARGUMENT";
                field = "args.operation_id";
                message = "A lowercase operation UUID is required";
            } else if (!eq(id, n->op.active ? n->op.id : n->last_operation)) {
                code = "INVALID_STATE";
                message = "Operation is not active or the most recent operation";
            } else
                action = STOP;
        } else if (eq(name, "hello") || eq(name, "status.get") || eq(name, "control.keepalive") ||
                   eq(name, "control.release")) {
            if (cJSON_GetArraySize(args)) {
                code = "INVALID_ARGUMENT";
                field = "args";
                message = "This command accepts no arguments";
            } else if (eq(name, "control.release") && (n->op.active || rf_execution_busy(&n->rf))) {
                code = "INVALID_STATE";
                message = "Stop the active operation before releasing ownership";
            } else if (eq(name, "control.release"))
                action = RELEASE;
            else if (eq(name, "control.keepalive"))
                action = KEEPALIVE;
        } else {
            code = known_unavailable(name) ? "MISSING_CAPABILITY" : "UNSUPPORTED_COMMAND";
            message = "Command is unavailable in this firmware";
        }
    }
    if (!code && (action == PROBE || action == BENCHMARK || action == PLAY || action == CAPTURE)) {
                    uint8_t id[16];
                    n->port.random_bytes(n->port.context, id, sizeof(id));
                    id[6] = (id[6] & 15) | 64;
                    id[8] = (id[8] & 63) | 128;
                    snprintf(operation_id, sizeof(operation_id),
                             "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
                             id[0], id[1], id[2], id[3], id[4], id[5], id[6], id[7], id[8], id[9],
                             id[10], id[11], id[12], id[13], id[14], id[15]);
    }
    if (!code && (action == CONFIGURE || (action == RF_COMMAND && !read))) {
        cJSON *failure = command_reply(n,cmd,sequence,NULL,"INTERNAL_ERROR",action==CONFIGURE?"Radio configuration failed":"Radio operation failed",NULL);
        if (!encode(n,failure) || strlen(n->encoded) >= sizeof(n->config_failure)) {
            n->reply_drops++; cJSON_Delete(radio_result); cJSON_Delete(cmd); return;
        }
        strcpy(n->config_failure,n->encoded);
    }
    if (!code) {
        if(action==RF_COMMAND)result=radio_result;
        else if (action == CONFIGURE) {
            result = radio_config_result(&radio_settings,&link_settings,n->config_revision+1);
            if (!result) n->oom = true;
        } else if (eq(name, "hello"))
            result = hello(n);
        else if (eq(name, "status.get"))
            result = health(n);
        else if (eq(name, "artifact.list"))
            result = artifact_list(n);
        else if (action == COMMIT_FILE) {
            artifact_manifest committed = *artifact_store_find(n->artifacts, text(args, "artifact_id"));
            committed.state = ARTIFACT_COMMITTED;
            result = manifest(n, &committed);
        }
        else {
            result = object(n);
            if (action == CLAIM || action == KEEPALIVE)
                number(n, result, "lease_expires_us", lease);
            if (action == CLAIM) number(n,result,"config_revision",n->config_revision);
            if (action == CLAIM || action == RELEASE)
                string(n, result, "state", n->op.active ? "running" : rf_execution_state(&n->rf));
            if (action == PROBE || action == BENCHMARK || action == PLAY || action == CAPTURE) {
                string(n, result, "operation_id", operation_id);
                string(n, result, "state", "accepted");
                number(n, result, "deadline_us", operation_deadline);
            }
            if (action == GET_FILE) {
                char encoded[((ARTIFACT_CHUNK_BYTES + 2) / 3) * 4 + 1], crc[9];
                chunk_base64_encode(chunk, chunk_length, encoded, sizeof(encoded));
                snprintf(crc, sizeof(crc), "%08" PRIx32, chunk_crc32(chunk, chunk_length));
                string(n, result, "artifact_id", text(args, "artifact_id"));
                number(n, result, "offset", chunk_offset);
                number(n, result, "length_bytes", chunk_length);
                string(n, result, "data_b64", encoded);
                string(n, result, "crc32", crc);
                boolean(n, result, "eof", chunk_eof);
            }
            if (action == RESERVE_FILE || action == DELETE_FILE || action == PUT_FILE) {
                string(n, result, "artifact_id", text(args, "artifact_id"));
                if (action == RESERVE_FILE || action == PUT_FILE)
                    number(n, result, "next_offset", action == RESERVE_FILE ? 0 : chunk_offset + chunk_length);
                else
                    boolean(n, result, "deleted", true);
            }
            if (action == STOP) {
                string(n, result, "operation_id", text(args, "operation_id"));
                string(n, result, "state", "idle"); // Cleanup is synchronous and bounded.
            }
        }
    }
    cJSON *reply = command_reply(n,cmd,sequence,result,code,message,field);
    if (!encode(n, reply)) {
        if (action == RESERVE_FILE)
            artifact_store_delete(n->artifacts, file_spec.artifact_id);
        if (capture_reserved) artifact_store_delete(n->artifacts, text(args, "artifact_id"));
        if (play_acquired) artifact_store_release(n->artifacts, text(args, "artifact_id"));
        if (probe)
            n->port.deallocate(n->port.context, probe);
        n->reply_drops++;
        n->diagnostics_pending++;
        cJSON_Delete(cmd);
        return;
    }
    bool cacheable = !read && (owned || (!code && action == CLAIM)) &&
                     !eq(code, "COMMAND_CONFLICT") && !eq(code, "COMMAND_EXPIRED") &&
                     !eq(code, "STALE_BOOT") && !eq(code, "UNSUPPORTED_VERSION") && valid_envelope;
    if (cacheable) {
        if (strlen(n->encoded) >= sizeof(n->cache[0].reply)) {
            if (action == RESERVE_FILE)
                artifact_store_delete(n->artifacts, file_spec.artifact_id);
            if (capture_reserved) artifact_store_delete(n->artifacts, text(args, "artifact_id"));
        if (play_acquired) artifact_store_release(n->artifacts, text(args, "artifact_id"));
            if (probe)
                n->port.deallocate(n->port.context, probe);
            n->reply_drops++;
            cJSON_Delete(cmd);
            return; // No effects without a replayable acceptance.
        }
        if(!code && action==RF_COMMAND) {
            strcpy(n->mutation_success,n->encoded);
            if(!rf_execution_apply(&n->rf,&radio_plan)) {code="INTERNAL_ERROR";message="Radio operation failed";strcpy(n->encoded,n->config_failure);}
            else strcpy(n->encoded,n->mutation_success);
        }
        if (!code && action == CONFIGURE) {
            if (!node_radio_configure(n->port.radio,&radio_settings)) {
                code="INTERNAL_ERROR"; message="Radio configuration failed";
                strcpy(n->encoded,n->config_failure);
            } else { n->link=link_settings; n->config_revision++; }
        }
        if (fresh_claim || action == RELEASE) {
            memset(n->cache, 0, sizeof(n->cache));
            n->cache_next = 0;
        }
        cached_reply *c = &n->cache[n->cache_next++ % NODE_CACHE_SLOTS];
        c->valid = true;
        c->key_setup = !code && eq(name, "session.open") && radio_plan.protected_mode;
        c->sequence = sequence;
        memcpy(c->hash, fingerprint, sizeof(c->hash));
        snprintf(c->client, sizeof(c->client), "%s", client);
        snprintf(c->command, sizeof(c->command), "%s", text(cmd, "command_id"));
        memcpy(c->reply, n->encoded, strlen(n->encoded) + 1);
    }
    if (valid_envelope && !eq(name, "hello") && (owned || (!code && action == CLAIM)) &&
        !eq(code, "STALE_BOOT") && !eq(code, "UNSUPPORTED_VERSION") &&
        !eq(code, "COMMAND_CONFLICT") && !eq(code, "COMMAND_EXPIRED")) {
        if (!mark)
            mark = watermark(n, client, true);
        if (mark) {
            snprintf(mark->client, sizeof(mark->client), "%s", client);
            if (sequence > mark->sequence)
                mark->sequence = sequence;
        }
    }
    send_reply(n, n->encoded); // Reserve correlation before performing effects.
    if (action == COMMIT_FILE)
        artifact_store_accept_commit(n->artifacts, text(args, "artifact_id"));
    if (code)
        remember_error(n, code, message);
    else if (action == CLAIM) {
        snprintf(n->owner, sizeof(n->owner), "%s", client);
        snprintf(n->role, sizeof(n->role), "%s", text(args, "node_role"));
        n->lease_until = lease;
    } else if (action == KEEPALIVE)
        n->lease_until = lease;
    else if (action == RELEASE) {
        rf_execution_abort(&n->rf,"host_shutdown",true);
        artifact_store_release_owner(n->artifacts, n->owner);
        n->owner[0] = n->role[0] = 0;
        n->lease_until = 0;
    } else if (action == PUT_FILE) {
        artifact_store_put(n->artifacts, text(args, "artifact_id"), chunk_offset,
                           chunk, chunk_length, chunk_crc);
    } else if (action == DELETE_FILE) {
        artifact_store_delete(n->artifacts, text(args, "artifact_id"));
    } else if (action == PROBE || action == BENCHMARK || action == PLAY || action == CAPTURE) {
        memset(&n->op, 0, sizeof(n->op));
        n->op.active = true;
        n->op.buffer = probe;
        n->op.iterations = iterations;
        n->op.bytes = bytes;
        n->op.started = now(n);
        n->op.deadline = operation_deadline;
        snprintf(n->op.id, sizeof(n->op.id), "%s", operation_id);
        const char *run_id = text(cmd, "run_id");
        if (run_id)
            snprintf(n->op.run_id, sizeof(n->op.run_id), "%s", run_id);
        if (action == BENCHMARK) {
            n->op.benchmark = true;
            n->op.crypto = crypto_benchmark_create(bytes, iterations, n->port.context, n->port.now_us);
            if (!n->op.crypto) finish_operation(n, "failed", "ALLOCATION_FAILED", "Benchmark public key setup failed");
        }
        if (action == PLAY || action == CAPTURE) {
            n->op.capture = action == CAPTURE;
            n->op.audio = true;
            snprintf(n->op.artifact_id, sizeof(n->op.artifact_id), "%s", text(args, "artifact_id"));
            if (!n->port.audio.start(n->port.context, (uint8_t *)play_bytes, bytes / 2, n->op.capture))
                finish_operation(n, "failed", "INTERNAL_ERROR", "Audio driver start failed");
        }
    } else if (action == STOP)
        finish_operation(n, "cancelled", NULL, "operator");
    cJSON_Delete(cmd);
}

static void *radio_allocate(void *context, size_t size) {node_control *n=context;return n->port.allocate(n->port.context,size);}
static void radio_release(void *context, void *bytes) {node_control *n=context;n->port.deallocate(n->port.context,bytes);}
static int64_t radio_now(void *context) {return now(context);}
static bool radio_hash(void *context,const void *bytes,size_t count,uint8_t out[32]) {node_control *n=context;return n->port.sha256(n->port.context,bytes,count,out);}
static void radio_random(void *context,void *bytes,size_t count) {node_control *n=context;n->port.random_bytes(n->port.context,bytes,count);}
static bool radio_emit(void *context,const char *name,cJSON *data,const char *run) {return emit(context,name,data,run);}
static uint64_t radio_drops(void *context) {return ((node_control *)context)->telemetry_drops;}
static bool radio_room(void *context,unsigned count) {node_control *n=context;return n->events.capacity-n->events.count>=count;}
node_control *node_control_create(const node_platform *platform)
{
    if (!platform || ((platform->audio.playback || platform->audio.capture) && (!platform->audio.start || !platform->audio.poll || !platform->audio.stop)) || !platform->now_us || !platform->sha256 || !platform->random_bytes ||
        !platform->allocate || !platform->deallocate || !platform->memory || !platform->device_id ||
        !platform->boot_id || !platform->firmware_version || !platform->firmware_build_id ||
        !platform->idf_version || !platform->reset_cause || !platform->board_manifest_hash ||
        !platform->schema_sha256)
        return NULL;
    secure_json_ensure();
    node_control *n = calloc(1, sizeof(*n));
    if (!n)
        return NULL;
    n->port = *platform;
    n->codec2_library_ready = codec2_dependency_query(platform->codec2_mode, &n->codec2_format);
    n->artifacts = artifact_store_create(platform->context, platform->allocate, platform->deallocate);
    if (!n->artifacts) {
        free(n);
        return NULL;
    }
    rf_execution_init(&n->rf,n->port.radio,n->artifacts,(rf_execution_port){n,radio_now,radio_hash,radio_random,radio_emit,radio_room,radio_drops,radio_allocate,radio_release});
    n->linked = true;
    n->replies.capacity = NODE_REPLY_SLOTS;
    n->events.capacity = NODE_EVENT_SLOTS;
    n->next_health = now(n) + 1000000;
    return n;
}
void node_control_destroy(node_control *n)
{
    if (!n)
        return;
    if (n->op.active) finish_operation(n, "cancelled", NULL, "shutdown");
    rf_execution_abort(&n->rf,"host_shutdown",true);
    if (!crypto_benchmark_destroy(&n->op.crypto)) return; // Retain failed cleanup for retry.
    artifact_store_destroy(n->artifacts);
    wipe_bytes(n, sizeof(*n));
    free(n);
}
void node_control_link(node_control *n, bool connected)
{
    if (n->linked && !connected) {
        n->link_losses++;
        lose_owner(n, "disconnect");
        wipe_bytes(n->line, sizeof(n->line));
        n->used = 0;
        n->discard = false;
        n->replies.count = n->events.count = 0;
        n->replies.head = n->events.head = 0;
    }
    n->linked = connected;
}
void node_control_tick(node_control *n)
{
    int64_t time = now(n);
    if (n->owner[0] && time >= n->lease_until)
        lose_owner(n, "lease_expired");
    if (!n->linked)
        return;
    n->oom=false;
    rf_execution_tick(&n->rf);
    operation *op = &n->op;
    if (!op->active && op->crypto) crypto_benchmark_destroy(&op->crypto);
    if (op->active && time >= op->deadline) {
        finish_operation(n, "failed", "TIMEOUT", "Operation deadline expired");
    } else if (op->active && op->benchmark) {
        // Pause at bounded queue pressure; never include serial work in a call sample.
        if (n->events.count + 2 <= n->events.capacity) {
            int64_t slice_start = now(n);
            for (unsigned i = 0; i < CRYPTO_BENCH_PAGE; i++) {
                crypto_benchmark_step(op->crypto);
                if (now(n) - slice_start >= 2000) break;
            }
            benchmark_page(n);
            crypto_benchmark_status progress = crypto_benchmark_progress(op->crypto);
            if (progress.failed) finish_operation(n, "failed", "INTERNAL_ERROR", "Benchmark output or timer verification failed");
            else if (progress.finished) finish_operation(n, "completed", NULL, NULL);
        }
    } else if (op->active && op->audio) {
        n->port.audio.poll(n->port.context, &op->audio_progress);
        if (op->audio_progress.failed)
            finish_operation(n, "failed", "INTERNAL_ERROR", "Audio DMA deadline missed");
        else if (op->audio_progress.done) {
            if (op->audio_progress.samples == op->bytes / 2)
                finish_operation(n, "completed", NULL, NULL);
            else finish_operation(n, "failed", "INTERNAL_ERROR", "Audio sample count mismatch");
        }
    } else if (op->active) {
        uint32_t end = op->offset + 512;
        if (end > op->bytes)
            end = op->bytes;
        for (uint32_t i = op->offset; i < end; i++) {
            uint8_t pattern = (uint8_t)(i ^ (i >> 8) ^ op->completed);
            if (!op->verifying)
                op->buffer[i] = pattern;
            else if (op->buffer[i] != pattern) {
                finish_operation(n, "failed", "INTERNAL_ERROR",
                                 "Diagnostic memory verification failed");
                break;
            }
        }
        if (op->active) {
            op->offset = end;
            if (end == op->bytes) {
                op->offset = 0;
                if (op->verifying)
                    op->completed++;
                op->verifying = !op->verifying;
                if (op->completed == op->iterations)
                    finish_operation(n, "completed", NULL, NULL);
            }
        }
    }
    if (time >= n->next_health) {
        n->oom = false;
        cJSON *data = health(n);
        emit(n, "health", data, n->op.active && n->op.run_id[0] ? n->op.run_id : rf_execution_busy(&n->rf)?n->rf.plan.run:NULL);
        n->next_health = time + 1000000;
    }
    if (n->diagnostics_pending && time >= n->next_diagnostic) {
        char message[161];
        snprintf(message, sizeof(message),
                 "Rejected input records: %" PRIu64 "; oversized=%" PRIu64 "; json=%" PRIu64
                 "; envelope=%" PRIu64,
                 n->diagnostics_pending, n->oversized, n->rejected_json, n->rejected_envelope);
        n->oom = false;
        cJSON *data = object(n);
        string(n, data, "severity", "warning");
        string(n, data, "code", "INVALID_ARGUMENT");
        string(n, data, "message", message);
        string(n, data, "related_command_id", NULL);
        emit(n, "diagnostic", data, NULL);
        n->diagnostics_pending = 0;
        n->next_diagnostic = time + 1000000;
    }
}
void node_control_feed(node_control *n, const uint8_t *bytes, size_t length)
{
    if (!n->linked)
        return;
    for (size_t i = 0; i < length; i++) {
        uint8_t byte = bytes[i];
        if (byte == '\n') {
            if (!n->discard) {
                if (n->used && n->line[n->used - 1] == '\r')
                    n->used--;
                n->line[n->used] = '\0';
                n->dispatching = true;
                node_control_tick(n); // Expire ownership before dispatch.
                process(n, n->used);
                n->dispatching = false;
            }
            wipe_bytes(n->line, sizeof(n->line));
            n->used = 0;
            n->discard = false;
        } else if (!n->discard) {
            if (n->used < sizeof(n->line) - 1)
                n->line[n->used++] = (char)byte;
            else {
                wipe_bytes(n->line, sizeof(n->line));
                n->used = 0;
                n->discard = true;
                n->oversized++;
                n->diagnostics_pending++;
            }
        }
    }
}
size_t node_control_output(node_control *n, char *destination, size_t capacity)
{
    record_queue *q = n->replies.count ? &n->replies : &n->events;
    if (!q->count || capacity < q->slots[q->head].length)
        return 0;
    record *r = &q->slots[q->head];
    size_t length = r->length;
    memcpy(destination, r->bytes, length);
    q->head = (q->head + 1) % q->capacity;
    q->count--;
    return length;
}
