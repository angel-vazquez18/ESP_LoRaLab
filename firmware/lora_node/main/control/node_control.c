#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "node_control.h"
#include "protocol/strict_json.h"

typedef struct {
    uint32_t sequence;
    uint8_t hash[32];
    char client[37], command[37], reply[1024];
    bool valid;
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
    bool active, verifying;
    char id[37], run_id[37];
    uint8_t *buffer;
    uint32_t iterations, completed, bytes, offset;
    int64_t started, deadline;
} operation;

struct node_control {
    node_platform port;
    char owner[37], role[2];
    int64_t lease_until, next_health, next_diagnostic;
    bool linked, oom, discard;
    size_t used;
    char line[NODE_RECORD_BYTES], encoded[NODE_RECORD_BYTES];
    record_queue replies, events;
    cached_reply cache[NODE_CACHE_SLOTS];
    unsigned cache_next;
    client_watermark clients[16]; // Never evict a sequence fence within a boot.
    operation op;
    char last_operation[37];
    uint64_t event_sequence, telemetry_drops, reply_drops;
    uint64_t rx_records, oversized, rejected_json, rejected_envelope, backpressure;
    uint64_t diagnostics_pending, link_losses, completed_operations;
    char error_code[40], error_message[161];
};

static int64_t now(node_control *n) { return n->port.now_us(n->port.context); }
static bool eq(const char *a, const char *b) { return a && b && !strcmp(a, b); }
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
static cJSON *capabilities(node_control *n)
{
    cJSON *o = object(n), *limits = object(n);
    static const char *const disabled[] = {
        "radio",         "audio_capture", "audio_playback", "codec2_3200", "security_gcm",
        "fragmentation", "ack_retry",     "echo",           "clock_sync",  "fault_injection"};
    for (size_t i = 0; i < sizeof(disabled) / sizeof(disabled[0]); i++)
        boolean(n, o, disabled[i], false);
    boolean(n, o, "memory_stats", true);
    add(n, o, "radio_limits", object(n));
    number(n, limits, "max_record_bytes", NODE_RECORD_BYTES);
    number(n, limits, "reply_queue_records", NODE_REPLY_SLOTS);
    number(n, limits, "telemetry_queue_records", NODE_EVENT_SLOTS);
    number(n, limits, "duplicate_cache_records", NODE_CACHE_SLOTS);
    number(n, limits, "max_clients_per_boot", 16);
    number(n, limits, "diag_max_iterations", 10000);
    number(n, limits, "diag_max_payload_bytes", NODE_PROBE_BYTES);
    number(n, limits, "operation_timeout_us", NODE_OPERATION_US);
    number(n, limits, "operation_slice_bytes", 512);
    cJSON *kinds = cJSON_CreateStringArray((const char *[]){"memory_probe"}, 1);
    add(n, limits, "diag_kinds", kinds);
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
    string(n, o, "state", n->op.active ? "running" : "idle");
    string(n, o, "run_id", n->op.active && n->op.run_id[0] ? n->op.run_id : NULL);
    string(n, o, "operation_id", n->op.active ? n->op.id : NULL);
    number(n, o, "uptime_us", now(n));
    string(n, o, "reset_cause", n->port.reset_cause);
    string(n, o, "radio", NULL);
    string(n, o, "link", NULL);
    number(n, o, "config_revision", 0);
    add(n, o, "capability_availability", capabilities(n));
    add(n, memory, "internal", heap(n, &internal));
    add(n, memory, "psram", heap(n, &psram));
    number(n, buffers, "serial_rx", n->used);
    number(n, buffers, "serial_tx_queued", queued_bytes(&n->replies) + queued_bytes(&n->events));
    number(n, buffers, "diagnostic", n->op.active ? n->op.bytes : 0);
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
    boolean(n, o, "security_ready", false);
    string(n, o, "audio_state", "not_supported");
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
    string(n, o, "state", n->op.active ? "running" : "idle");
    return o;
}
static void emit(node_control *n, const char *name, cJSON *data, const char *run_id)
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
    if (!encode(n, o) || !enqueue(&n->events, n->encoded))
        n->telemetry_drops++;
}
static void remember_error(node_control *n, const char *code, const char *message)
{
    snprintf(n->error_code, sizeof(n->error_code), "%s", code);
    snprintf(n->error_message, sizeof(n->error_message), "%s", message);
}
static void finish_operation(node_control *n, const char *status, const char *code,
                             const char *message)
{
    if (!n->op.active)
        return;
    operation *op = &n->op;
    n->port.deallocate(n->port.context, op->buffer);
    op->buffer = NULL;
    op->active = false;
    snprintf(n->last_operation, sizeof(n->last_operation), "%s", op->id);
    if (eq(status, "completed"))
        n->completed_operations++;
    if (code)
        remember_error(n, code, message);
    n->oom = false;
    cJSON *data = object(n), *result = code ? cJSON_CreateNull() : object(n);
    if (!code) {
        string(n, result, "kind", "memory_probe");
        number(n, result, "iterations_completed", op->completed);
        number(n, result, "payload_bytes", op->bytes);
        number(n, result, "verified_bytes", (uint64_t)op->completed * op->bytes);
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
    n->owner[0] = n->role[0] = 0;
    n->lease_until = 0;
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
        "run.start",       "run.stop",      "run.summary",   "artifact.begin",  "artifact.put",
        "artifact.commit", "artifact.list", "artifact.get",  "artifact.delete", "audio.capture",
        "audio.encode",    "audio.decode",  "audio.play",    "fault.set",       "fault.fire",
        "clock.arm",       "clock.emit",    "clock.install", "clock.stop"};
    for (size_t i = 0; i < sizeof(commands) / sizeof(commands[0]); i++)
        if (eq(name, commands[i]))
            return true;
    return false;
}

enum action { NONE, CLAIM, KEEPALIVE, RELEASE, PROBE, STOP };
static void process(node_control *n, size_t length)
{
    n->rx_records++;
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
    bool read = eq(name, "hello") || eq(name, "status.get");
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
    if (!code && !eq(name, "diag.run") && !cJSON_IsNull(item(cmd, "run_id"))) {
        code = "INVALID_ARGUMENT";
        field = "run_id";
        message = "Control commands require null run_id";
    }
    enum action action = NONE;
    uint8_t *probe = NULL;
    uint32_t iterations = 0, bytes = 0;
    int64_t lease = now(n) + 5000000;
    int64_t operation_deadline = now(n) + NODE_OPERATION_US;
    char operation_id[37] = {0};
    bool fresh_claim = false;
    n->oom = false;
    cJSON *result = NULL;
    if (!code) {
        if (eq(name, "control.claim")) {
            const char *const keys[] = {"node_role"};
            if (!exact_keys(args, keys, 1) ||
                (!eq(text(args, "node_role"), "A") && !eq(text(args, "node_role"), "B"))) {
                code = "INVALID_ARGUMENT";
                field = "args.node_role";
                message = "Choose node role A or B";
            } else if (n->owner[0] && !owned) {
                code = "BUSY";
                message = "Another client owns this node";
            } else if (n->op.active && !eq(text(args, "node_role"), n->role)) {
                code = "INVALID_STATE";
                message = "Role changes require an idle node";
            } else if (!(mark = watermark(n, client, true))) {
                code = "RESOURCE_LIMIT";
                message = "Client sequence table full; reset required";
            } else {
                action = CLAIM;
                fresh_claim = !n->owner[0];
            }
        } else if (eq(name, "diag.run")) {
            const char *const keys[] = {"kind", "iterations", "payload_bytes"};
            if (!exact_keys(args, keys, 3) || !text(args, "kind") ||
                !uint32_value(item(args, "iterations"), 1, 10000) ||
                !uint32_value(item(args, "payload_bytes"), 1, NODE_PROBE_BYTES)) {
                code = "INVALID_ARGUMENT";
                field = "args";
                message = "Invalid diagnostic kind or bounded workload";
            } else if (!eq(text(args, "kind"), "memory_probe")) {
                code = "MISSING_CAPABILITY";
                message = "Only memory_probe diagnostics are implemented";
            } else if (n->op.active) {
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
                    uint8_t id[16];
                    n->port.random_bytes(n->port.context, id, sizeof(id));
                    id[6] = (id[6] & 15) | 64;
                    id[8] = (id[8] & 63) | 128;
                    snprintf(operation_id, sizeof(operation_id),
                             "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
                             id[0], id[1], id[2], id[3], id[4], id[5], id[6], id[7], id[8], id[9],
                             id[10], id[11], id[12], id[13], id[14], id[15]);
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
            } else if (eq(name, "control.release") && n->op.active) {
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
    if (!code) {
        if (eq(name, "hello"))
            result = hello(n);
        else if (eq(name, "status.get"))
            result = health(n);
        else {
            result = object(n);
            if (action == CLAIM || action == KEEPALIVE)
                number(n, result, "lease_expires_us", lease);
            if (action == CLAIM || action == RELEASE)
                string(n, result, "state", n->op.active ? "running" : "idle");
            if (action == PROBE) {
                string(n, result, "operation_id", operation_id);
                string(n, result, "state", "accepted");
                number(n, result, "deadline_us", operation_deadline);
            }
            if (action == STOP) {
                string(n, result, "operation_id", text(args, "operation_id"));
                string(n, result, "state", "idle"); // Cleanup is synchronous and bounded.
            }
        }
    }
    cJSON *reply = object(n);
    number(n, reply, "v", 2);
    string(n, reply, "kind", "reply");
    string(n, reply, "command_id", text(cmd, "command_id"));
    number(n, reply, "command_seq", sequence);
    string(n, reply, "device_id", n->port.device_id);
    string(n, reply, "boot_id", n->port.boot_id);
    number(n, reply, "uptime_us", now(n));
    boolean(n, reply, "ok", code == NULL);
    add(n, reply, "result", result ? result : cJSON_CreateNull());
    add(n, reply, "error", error(n, code, message, field));
    if (!encode(n, reply)) {
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
            if (probe)
                n->port.deallocate(n->port.context, probe);
            n->reply_drops++;
            cJSON_Delete(cmd);
            return; // No effects without a replayable acceptance.
        }
        if (fresh_claim || action == RELEASE) {
            memset(n->cache, 0, sizeof(n->cache));
            n->cache_next = 0;
        }
        cached_reply *c = &n->cache[n->cache_next++ % NODE_CACHE_SLOTS];
        c->valid = true;
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
    if (code)
        remember_error(n, code, message);
    else if (action == CLAIM) {
        snprintf(n->owner, sizeof(n->owner), "%s", client);
        snprintf(n->role, sizeof(n->role), "%s", text(args, "node_role"));
        n->lease_until = lease;
    } else if (action == KEEPALIVE)
        n->lease_until = lease;
    else if (action == RELEASE) {
        n->owner[0] = n->role[0] = 0;
        n->lease_until = 0;
    } else if (action == PROBE) {
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
    } else if (action == STOP)
        finish_operation(n, "cancelled", NULL, "operator");
    cJSON_Delete(cmd);
}

node_control *node_control_create(const node_platform *platform)
{
    if (!platform || !platform->now_us || !platform->sha256 || !platform->random_bytes ||
        !platform->allocate || !platform->deallocate || !platform->memory || !platform->device_id ||
        !platform->boot_id || !platform->firmware_version || !platform->firmware_build_id ||
        !platform->idf_version || !platform->reset_cause || !platform->board_manifest_hash ||
        !platform->schema_sha256)
        return NULL;
    node_control *n = calloc(1, sizeof(*n));
    if (!n)
        return NULL;
    n->port = *platform;
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
    if (n->op.buffer)
        n->port.deallocate(n->port.context, n->op.buffer);
    free(n);
}
void node_control_link(node_control *n, bool connected)
{
    if (n->linked && !connected) {
        n->link_losses++;
        lose_owner(n, "disconnect");
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
    operation *op = &n->op;
    if (op->active && time >= op->deadline) {
        finish_operation(n, "failed", "TIMEOUT", "Diagnostic operation deadline expired");
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
        emit(n, "health", data, n->op.active && n->op.run_id[0] ? n->op.run_id : NULL);
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
                node_control_tick(n); // Expire ownership before dispatch.
                process(n, n->used);
            }
            n->used = 0;
            n->discard = false;
        } else if (!n->discard) {
            if (n->used < sizeof(n->line) - 1)
                n->line[n->used++] = (char)byte;
            else {
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
