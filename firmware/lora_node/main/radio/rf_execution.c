#include "radio/rf_execution.h"
#include "generated/execution_profile.h"
#include "protocol/chunk_bytes.h"
#include "protocol/strict_json.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *names[] = {"session.open", "session.close", "run.prepare", "run.arm",
                              "run.start",    "run.stop",      "run.summary", "run.source",
                              "fault.set", "fault.fire", "fault.status"};
static const char *text(const cJSON *o, const char *k)
{
    return cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
}
static bool eq(const char *a, const char *b) { return a && b && !strcmp(a, b); }
static cJSON *object(rf_execution *r)
{
    cJSON *v = cJSON_CreateObject();
    if (!v)
        r->oom = true;
    return v;
}
static void add(rf_execution *r, cJSON *o, const char *key, cJSON *value)
{
    if (!o || !value || !cJSON_AddItemToObject(o, key, value))
    {
        cJSON_Delete(value);
        r->oom = true;
    }
}
static void number(rf_execution *r, cJSON *o, const char *key, int64_t n)
{
    add(r, o, key, cJSON_CreateNumber(n));
}
static void string(rf_execution *r, cJSON *o, const char *key, const char *s)
{
    add(r, o, key, s ? cJSON_CreateString(s) : cJSON_CreateNull());
}
static bool send(rf_execution *r, const char *name, cJSON *o)
{
    if (r->oom)
    {
        cJSON_Delete(o);
        o = NULL;
    }
    return r->port.emit(r->port.context, name, o, r->plan.run);
}
static bool allowed(const cJSON *o, const char *const *keys, unsigned count)
{
    if (!cJSON_IsObject(o))
        return false;
    for (const cJSON *v = o->child; v; v = v->next)
    {
        unsigned i = 0;
        while (i < count && strcmp(v->string, keys[i]))
            i++;
        if (i == count)
            return false;
    }
    return true;
}
static bool integer(const cJSON *o, const char *k, uint32_t lo, uint32_t hi, uint32_t fallback,
                    uint32_t *out)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, k);
    if (!v)
    {
        *out = fallback;
        return true;
    }
    if (!strict_json_integer(v) || v->valuedouble < lo || v->valuedouble > hi)
        return false;
    *out = v->valuedouble;
    return true;
}
static bool literal(const cJSON *o, const char *k, const char *s)
{
    return !cJSON_GetObjectItemCaseSensitive(o, k) || eq(text(o, k), s);
}
static bool null_value(const cJSON *o, const char *k)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, k);
    return !v || cJSON_IsNull(v);
}
static bool source_text(const char *value, size_t length)
{
    if (!value || strlen(value) != length) return false;
    for (size_t i = 0; i < length; i++) {
        if (length == 36 && (i == 8 || i == 13 || i == 18 || i == 23)) {
            if (value[i] != '-') return false;
        } else if (!((value[i] >= '0' && value[i] <= '9') || (value[i] >= 'a' && value[i] <= 'f')))
            return false;
    }
    return true;
}
static void decode_hash(const char *value, uint8_t out[32])
{
    for (unsigned i = 0; i < 32; i++) {
        unsigned a = value[2 * i], b = value[2 * i + 1];
        out[i] = ((a <= '9' ? a - '0' : a - 'a' + 10) << 4) |
                  (b <= '9' ? b - '0' : b - 'a' + 10);
    }
}
static bool key_text(const char *key)
{
    if (!key || strlen(key) != 32)
        return false;
    for (unsigned i = 0; i < 32; i++)
        if (!((key[i] >= '0' && key[i] <= '9') || (key[i] >= 'a' && key[i] <= 'f')))
            return false;
    return true;
}
static void decode_key(const char *key, uint8_t out[16])
{
    for (unsigned i = 0; i < 16; i++)
    {
        uint8_t a = key[i * 2], b = key[i * 2 + 1];
        out[i] = ((a <= '9' ? a - '0' : a - 'a' + 10) << 4) | (b <= '9' ? b - '0' : b - 'a' + 10);
    }
}
bool rf_execution_security_ready(const rf_execution *r)
{
    return r->plan.protected_mode && rf_secure_ready(r->security);
}
static bool boolean(const cJSON *o, const char *k, bool expected)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, k);
    return !v || (expected ? cJSON_IsTrue(v) : cJSON_IsFalse(v));
}
static bool peer(const char *device, const char *boot)
{
    if (!device || strlen(device) != 16 || strncmp(device, "esp-", 4) || !boot ||
        strncmp(boot, device, 16) || boot[16] != ':' || boot[17] < '1' || boot[17] > '9')
        return false;
    for (unsigned i = 4; i < 16; i++)
        if (!((device[i] >= '0' && device[i] <= '9') || (device[i] >= 'a' && device[i] <= 'f')))
            return false;
    uint64_t n = 0;
    for (unsigned i = 17; boot[i]; i++)
    {
        if (boot[i] < '0' || boot[i] > '9' || i > 26)
            return false;
        n = n * 10 + boot[i] - '0';
    }
    return n <= UINT32_MAX;
}
static void uuid(rf_execution *r, char out[37])
{
    uint8_t b[16];
    r->port.random(r->port.context, b, 16);
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    snprintf(out, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x", b[0],
             b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13],
             b[14], b[15]);
}
static void hex(const uint8_t *digest, char out[65])
{
    for (unsigned i = 0; i < 32; i++)
        snprintf(out + i * 2, 3, "%02x", digest[i]);
}
static cJSON *budget(rf_execution *r, const rf_plan *p)
{
    cJSON *o = object(r);
    number(r, o, "ack_timeout_us", p->ack_timeout);
    number(r, o, "reassembly_timeout_us", p->reassembly);
    number(r, o, "drain_us", p->drain);
    number(r, o, "processing_budget_us", p->processing);
    number(r, o, "capture_budget_us", 0);
    number(r, o, "playback_budget_us", 0);
    number(r, o, "fault_budget_us", p->fault_us);
    string(r, o, "model_version", "sx126x_lora_v1");
    return o;
}
static uint32_t source_taken(rf_execution *r)
{ encoded_source_status s = {0}; if (r->queue) encoded_queue_snapshot(r->queue, &s); return s.taken_messages; }
static uint32_t source_failed(rf_execution *r)
{ encoded_source_status s = {0}; if (r->queue) encoded_queue_snapshot(r->queue, &s); return s.failed_messages; }
static uint32_t source_produced(rf_execution *r)
{ encoded_source_status s = {0}; if (r->queue) encoded_queue_snapshot(r->queue, &s); return s.produced_bytes; }
static cJSON *source_status(rf_execution *r, const encoded_source_status *s)
{
    cJSON *o = object(r);
    number(r, o, "started_us", s->started_us);
    number(r, o, "production_end_us", s->production_end_us);
    number(r, o, "drain_deadline_us", s->drain_deadline_us);
#define FIELD(name) number(r, o, #name, s->name);
    SOURCE_COUNTERS(FIELD)
#undef FIELD
    add(r, o, "drain_cutoff", cJSON_CreateBool(s->drain_cutoff));
    add(r, o, "consistent", cJSON_CreateBool(s->consistent));
    add(r, o, "cancel_requested", cJSON_CreateBool(s->cancel_requested));
    return o;
}
static const char *source_query(rf_execution *r, const cJSON *args, cJSON **result)
{
    const char *const keys[] = {"view", "offset", "limit"};
    const char *view = text(args, "view"); if (!view) view = "status";
    uint32_t offset, limit;
    if (!allowed(args, keys, 3) || (!eq(view,"status") && !eq(view,"frames") && !eq(view,"samples")) ||
        !integer(args,"offset",0,3000,0,&offset) || !integer(args,"limit",1,16,1,&limit) ||
        (eq(view,"samples") && limit != 1)) return "INVALID_ARGUMENT";
    cJSON *o = object(r), *frames = cJSON_CreateArray(), *samples = cJSON_CreateArray(), *ids = cJSON_CreateArray();
    encoded_source_status status;
    if (r->queue) { encoded_queue_snapshot(r->queue, &status); add(r,o,"status",source_status(r,&status)); }
    else add(r,o,"status",cJSON_CreateNull());
    for (unsigned i = 0; i < 20; i++) if (r->delivered_bitmap & (1U << i)) {
        if (!ids || !cJSON_AddItemToArray(ids,cJSON_CreateNumber(i+1))) r->oom = true;
    }
    add(r,o,"delivered_message_ids",ids);
    string(r,o,"archive_artifact_id", !r->sender && r->artifact_reserved ? r->artifact_id : NULL);
    string(r,o,"archive_sha256", r->archive_sha[0] ? r->archive_sha : NULL);
    string(r,o,"view",view); number(r,o,"offset",offset);
    size_t count = 0;
    if (r->queue && eq(view,"frames")) {
        encoded_source_trace rows[16]; count = encoded_queue_trace(r->queue,offset,rows,limit);
        for (size_t i=0;i<count;i++) {
            cJSON *row=object(r); number(r,row,"index",rows[i].index);
            number(r,row,"planned_elapsed_us",rows[i].planned_elapsed_us);
            if (rows[i].produced) number(r,row,"actual_elapsed_us",rows[i].actual_elapsed_us);
            else string(r,row,"actual_elapsed_us",NULL);
            add(r,row,"produced",cJSON_CreateBool(rows[i].produced));
            if (!frames || !cJSON_AddItemToArray(frames,row)) { cJSON_Delete(row); r->oom=true; }
        }
    } else if (r->queue && eq(view,"samples")) {
        encoded_source_sample sample; count=encoded_queue_samples(r->queue,offset,&sample,1);
        if (count) {
            cJSON *row=object(r); number(r,row,"index",sample.index);
            number(r,row,"planned_elapsed_us",sample.planned_elapsed_us);
            number(r,row,"actual_elapsed_us",sample.actual_elapsed_us);
            number(r,row,"missed_intervals",sample.missed_intervals);
            add(r,row,"status",source_status(r,&sample.status));
            if (!samples || !cJSON_AddItemToArray(samples,row)) { cJSON_Delete(row); r->oom=true; }
        }
    }
    number(r,o,"next_offset",offset+count);
    add(r,o,"eof",cJSON_CreateBool(count < limit));
    add(r,o,"frames",frames); add(r,o,"samples",samples);
    *result=o;
    return NULL;
}
static cJSON *echo_result(rf_execution *r)
{
    rf_echo_status s = r->echo_status;
    if (r->echo) rf_echo_snapshot(r->echo, &s);
    cJSON *o = object(r);
    string(r, o, "session_id", r->plan.session_text);
    if (s.request_sequence) number(r, o, "request_frame_seq", s.request_sequence);
    else string(r, o, "request_frame_seq", NULL);
    if (s.reply_sequence) number(r, o, "reply_frame_seq", s.reply_sequence);
    else string(r, o, "reply_frame_seq", NULL);
    number(r, o, "payload_bytes", r->plan.bytes);
    string(r, o, "payload_sha256", r->sha_hex);
    string(r, o, "reply_hex", s.valid ? r->echo_reply_hex : NULL);
    if (s.tx_command_us >= 0) number(r, o, "tx_command_us", s.tx_command_us);
    else string(r, o, "tx_command_us", NULL);
    if (s.valid) {
        number(r, o, "reply_accepted_us", s.accepted_us);
        number(r, o, "rtt_us", s.accepted_us - s.tx_command_us);
    } else {
        string(r, o, "reply_accepted_us", NULL);
        string(r, o, "rtt_us", NULL);
    }
    add(r, o, "valid", cJSON_CreateBool(s.valid));
    string(r, o, "reason", s.reason ? s.reason : "not_started");
    return o;
}
static cJSON *summary(rf_execution *r)
{
    cJSON *o = object(r);
    if (r->plan.echo) add(r, o, "echo", echo_result(r));
    string(r, o, "role", r->sender ? "sender" : "receiver");
    string(r, o, "session_id", r->plan.session_text);
    number(r, o, "config_revision", r->plan.revision);
    number(r, o, "intended_messages", r->plan.fixed_source ? 20 : 1);
    number(r, o, "started_messages", r->plan.fixed_source ? r->sender ? source_taken(r) : r->received_messages : r->started);
    number(r, o, "finished_messages", r->plan.fixed_source ? r->sender ? r->source_finished_messages : r->delivered : r->finished && r->started);
    number(r, o, "original_packets", r->originals);
    number(r, o, "tx_attempts", r->attempts);
    number(r, o, "radio_observations", r->observations);
    number(r, o, "accepted_fragments", r->accepted);
    number(r, o, "duplicates", r->duplicates);
    number(r, o, "delivered_messages", r->delivered);
    number(r, o, "failed_messages", r->plan.fixed_source ? r->sender ? source_failed(r) :
        r->finished ? r->received_messages - r->delivered : 0 : r->failed && r->started && !r->delivered);
    number(r, o, "useful_source_bytes", r->sender ? r->plan.fixed_source ? source_produced(r) : r->plan.bytes : 0);
    number(r, o, "useful_delivered_bytes", r->delivered * r->plan.bytes);
    if (r->first_tx >= 0)
        number(r, o, "first_tx_command_us", r->first_tx);
    else
        string(r, o, "first_tx_command_us", NULL);
    if (r->last_tx >= 0)
        number(r, o, "last_tx_done_us", r->last_tx);
    else
        string(r, o, "last_tx_done_us", NULL);
    if (r->first_rx >= 0)
        number(r, o, "first_rx_us", r->first_rx);
    else
        string(r, o, "first_rx_us", NULL);
    if (r->last_rx >= 0)
        number(r, o, "last_rx_us", r->last_rx);
    else
        string(r, o, "last_rx_us", NULL);
    string(r, o, "stop_reason", r->stop_reason ? r->stop_reason : "operator");
    cJSON *cleanup = cJSON_CreateArray();
    const char *errors[] = {r->radio_cleanup_failed ? "RADIO_STOP_FAILED" : NULL,
                            r->key_cleanup_failed ? "KEY_RETIRE_FAILED" : NULL,
                            r->source_cleanup_failed ? "SOURCE_STOP_FAILED" : NULL};
    for (unsigned i = 0; i < 3; i++) if (errors[i]) {
        cJSON *error = cJSON_CreateString(errors[i]);
        if (!error || !cleanup || !cJSON_AddItemToArray(cleanup, error)) {
            cJSON_Delete(error);
            r->oom = true;
        }
    }
    add(r, o, "cleanup_errors", cleanup);
    number(r, o, "telemetry_drops", r->port.drops(r->port.context) - r->drops_start);
    cJSON *validity = cJSON_CreateArray();
    if (r->missing_evidence_incomplete && validity)
    {
        cJSON *reason = cJSON_CreateString("missing_range_evidence_incomplete");
        if (!reason || !cJSON_AddItemToArray(validity, reason))
        {
            cJSON_Delete(reason);
            r->oom = true;
        }
    }
    add(r, o, "validity_reasons", validity);
    return o;
}
static void state(rf_execution *r)
{
    cJSON *o = object(r);
    string(r, o, "state", rf_execution_state(r));
    string(r, o, "reason", NULL);
    number(r, o, "config_revision", r->plan.revision);
    send(r, "run.state", o);
}
static void operation(rf_execution *r, bool ok, cJSON *result)
{
    bool cancelled =
        !ok && (eq(r->stop_reason, "operator") || eq(r->stop_reason, "host_shutdown") ||
                eq(r->stop_reason, "peer_failure"));
    if (cancelled && !result)
    {
        result = object(r);
        string(r, result, "reason", r->stop_reason);
    }
    cJSON *o = object(r);
    string(r, o, "operation_id", r->plan.operation);
    string(r, o, "status", ok ? "completed" : cancelled ? "cancelled" : "failed");
    add(r, o, "result", result ? result : cJSON_CreateNull());
    cJSON *error = NULL;
    if (!ok && !cancelled)
    {
        error = object(r);
        string(r, error, "code", eq(r->stop_reason, "timeout") ? "TIMEOUT" : "INTERNAL_ERROR");
        string(r, error, "message", "Finite radio operation failed");
        string(r, error, "field", NULL);
        add(r, error, "retryable", cJSON_CreateFalse());
    }
    add(r, o, "error", error ? error : cJSON_CreateNull());
    send(r, "operation.result", o);
}
static uint32_t duplicate_guard(const node_link_settings *link)
{
    return link->guard_us > RF_FAULT_DUPLICATE_GUARD_US ?
        link->guard_us : RF_FAULT_DUPLICATE_GUARD_US;
}

static void retained_budget(const rf_execution *r, const rf_message_plan *packet,
                            const node_link_settings *link, const rf_fault_spec *spec,
                            uint64_t *total, bool *needs_barrier)
{
    if (spec->action != RF_FAULT_REPLAY && spec->action != RF_FAULT_DUPLICATE) return;
    unsigned body = spec->fragment + 1 < packet->fragment_count ? packet->fragment_bytes :
        packet->message_bytes - spec->fragment * packet->fragment_bytes;
    unsigned wire = RF_HEADER_BYTES + body + ((packet->flags & 1) ? RF_TAG_BYTES : 0);
    *total += rf_radio_airtime_us(&r->radio->applied, wire) + 80000;
    if (spec->action == RF_FAULT_REPLAY) *needs_barrier = true;
    else *total += duplicate_guard(link);
}

static bool fire_window(const rf_execution *r)
{
    return r->port.lab_faults && r->sender && r->phase == RF_DRAINING && r->plan.fault_us &&
        !r->injected_tx && r->port.now_us(r->port.context) < r->drain_deadline;
}
static const char *fault_command(rf_execution *r, const cJSON *args, rf_plan *p, cJSON **result)
{
    if (!r->port.lab_faults || !r->faults) return "MISSING_CAPABILITY";
    if (p->action == RF_FAULT_SET) {
        rf_fault_spec specs[RF_FAULT_BATCH]; size_t count; bool replace;
        if (!rf_fault_json_parse(args, specs, &count, &replace)) return "INVALID_ARGUMENT";
        if ((r->phase != RF_IDLE && r->phase != RF_PREPARED) || (r->used && r->phase == RF_IDLE && count))
            return "INVALID_STATE";
        unsigned total = (replace ? 0 : rf_faults_count(r->faults)) + count;
        if (total > RF_FAULT_ENTRIES) return "RESOURCE_LIMIT";
        if (count && r->phase == RF_PREPARED &&
            (r->plan.encoded || r->plan.echo || r->plan.fixed_source)) return "INVALID_ARGUMENT";
        if (!r->plan.protected_mode)
            for (size_t i = 0; i < count; i++)
                if (specs[i].action == RF_FAULT_XOR || specs[i].action == RF_FAULT_REPLAY)
                    return "INVALID_ARGUMENT";
        if (!rf_faults_can_configure(r->faults, specs, count, replace)) return "INVALID_ARGUMENT";
        if (r->phase == RF_PREPARED) {
            uint64_t required = 0;
            bool barrier = false;
            unsigned prior = replace ? 0 : rf_faults_count(r->faults);
            for (size_t i = 0; i < prior + count; i++) {
                rf_fault_view view;
                if (i < prior) rf_faults_view(r->faults, i, &view);
                const rf_fault_spec *spec = i < prior ? &view.spec : &specs[i - prior];
                retained_budget(r, &r->fragments, &r->plan.link, spec, &required, &barrier);
            }
            if (r->plan.fault_us < required + (barrier ? 1000000 : 0))
                return "INVALID_ARGUMENT";
        }
        p->fault_arguments = args;
        *result = object(r); number(r, *result, "count", total);
    } else if (p->action == RF_FAULT_STATUS) {
        const char *const keys[] = {"offset", "limit"};
        uint32_t offset, limit;
        if (!allowed(args, keys, 2) || !integer(args, "offset", 0, 32, 0, &offset) ||
            !integer(args, "limit", 4, 4, 4, &limit)) return "INVALID_ARGUMENT";
        unsigned count = rf_faults_count(r->faults), end = offset;
        cJSON *rows = cJSON_CreateArray();
        for (; end < count && end < offset + limit; end++) {
            rf_fault_view view; rf_faults_view(r->faults, end, &view);
            cJSON *row = rf_fault_json_entry(&view);
            if (!rows || !row || !cJSON_AddItemToArray(rows, row)) { cJSON_Delete(row); r->oom = true; break; }
        }
        *result = object(r);
        string(r, *result, "session_id", r->plan.session_text);
        number(r, *result, "count", count); number(r, *result, "offset", offset);
        number(r, *result, "next_offset", end);
        add(r, *result, "eof", cJSON_CreateBool(end >= count));
        add(r, *result, "fire_window_open", cJSON_CreateBool(fire_window(r)));
        add(r, *result, "entries", rows);
    } else {
        const char *const keys[] = {"injection_id"};
        const char *id = text(args, "injection_id"); size_t bytes;
        if (!allowed(args, keys, 1) || cJSON_GetArraySize(args) != 1 || !id || strlen(id) != 36)
            return "INVALID_ARGUMENT";
        const uint8_t *wire = rf_faults_replay(r->faults, id, &bytes);
        if (!fire_window(r) || !wire || !rf_secure_ready(r->security)) return "INVALID_STATE";
        uint32_t timeout = rf_radio_airtime_us(&r->radio->applied, bytes) + 80000;
        if (r->drain_deadline - r->port.now_us(r->port.context) < timeout) return "TIMEOUT";
        uint8_t digest[32]; char sha[65];
        if (!r->port.hash(r->port.context, wire, bytes, digest)) return "INTERNAL_ERROR";
        hex(digest, sha);
        p->fault_arguments = args;
        *result = object(r); string(r, *result, "injection_id", id);
        number(r, *result, "frame_seq", (uint32_t)wire[16] << 24 | (uint32_t)wire[17] << 16 | (uint32_t)wire[18] << 8 | wire[19]);
        number(r, *result, "frame_bytes", bytes); string(r, *result, "sha256", sha);
        string(r, *result, "status", "submitted");
    }
    if (r->oom) { cJSON_Delete(*result); *result = NULL; }
    return NULL;
}
void rf_execution_init(rf_execution *r, node_radio *radio, artifact_store *artifacts,
                       rf_execution_port port)
{
    *r = (rf_execution){.port = port,
                        .radio = radio,
                        .artifacts = artifacts,
                        .first_tx = -1,
                        .last_tx = -1,
                        .first_rx = -1,
                        .last_rx = -1};
}
bool rf_execution_command(const char *name)
{
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++)
        if (eq(name, names[i]))
            return true;
    return false;
}
bool rf_execution_busy(const rf_execution *r) { return r->phase != RF_IDLE || r->source_cleanup_failed; }
const char *rf_execution_state(const rf_execution *r)
{
    if (r->source_cleanup_failed) return "stopping";
    return (const char *[]){"idle",    "preparing", "prepared", "armed",
                            "running", "draining",  "stopping"}[r->phase];
}
const char *rf_execution_check(rf_execution *r, const char *name, const cJSON *args,
                               const char *run, const char *owner, const char *role,
                               const char *device, uint32_t revision,
                               const node_link_settings *link, const char *op, rf_plan *p,
                               cJSON **result)
{
    r->oom = false;
    *result = NULL;
    *p = r->plan;
    unsigned action = 0;
    while (action < sizeof(names) / sizeof(names[0]) && !eq(name, names[action]))
        action++;
    if (action == sizeof(names) / sizeof(names[0]))
        return "UNSUPPORTED_COMMAND";
    p->action = (rf_action)action;
    if (!run)
        return "INVALID_ARGUMENT";
    if (action != RF_OPEN && (!r->plan.session || !eq(run, r->plan.run)))
        return "INVALID_STATE";
    if (action != RF_CLOSE && action != RF_STOP && action != RF_SUMMARY && action != RF_SOURCE && action != RF_FAULT_STATUS &&
        (!r->radio || !r->radio->available))
        return "MISSING_CAPABILITY";
    if (action >= RF_FAULT_SET) return fault_command(r, args, p, result);
    if (action == RF_OPEN)
    {
        const char *const keys[] = {"session_id", "peer_device_id", "peer_boot_id",
                                    "security",   "tx_key_hex",     "rx_key_hex"};
        const char *session = text(args, "session_id"), *pd = text(args, "peer_device_id"),
                   *pb = text(args, "peer_boot_id");
        if (r->plan.session || rf_execution_busy(r))
            return "INVALID_STATE";
        if (!allowed(args, keys, 6) || cJSON_GetArraySize(args) != 6 || !session ||
            strlen(session) != 16 || !peer(pd, pb) || eq(pd, device) ||
            (!eq(text(args, "security"), "none") && !eq(text(args, "security"), "aes128_gcm")))
            return "INVALID_ARGUMENT";
        p->protected_mode = eq(text(args, "security"), "aes128_gcm");
        p->provision_keys = p->protected_mode ? args : NULL;
        if (p->protected_mode)
        {
            if (!key_text(text(args, "tx_key_hex")) || !key_text(text(args, "rx_key_hex")) ||
                eq(text(args, "tx_key_hex"), text(args, "rx_key_hex")))
                return "INVALID_ARGUMENT";
        }
        else if (!null_value(args, "tx_key_hex") || !null_value(args, "rx_key_hex"))
            return "INVALID_ARGUMENT";
        uint64_t id = 0;
        for (unsigned i = 0; i < 16; i++)
        {
            char c = session[i];
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
                return "INVALID_ARGUMENT";
            id = (id << 4) | (c <= '9' ? c - '0' : c - 'a' + 10);
        }
        if (!id)
            return "INVALID_ARGUMENT";
        p->session = id;
        snprintf(p->session_text, 17, "%s", session);
        snprintf(p->run, 37, "%s", run);
        snprintf(p->owner, 37, "%s", owner);
        snprintf(p->peer_device, 17, "%s", pd);
        snprintf(p->peer_boot, 32, "%s", pb);
        p->role = eq(role, "A") ? 1 : 2;
    }
    else if (action == RF_PREPARE)
    {
        if (r->plan.protected_mode && !rf_secure_ready(r->security))
            return "KEY_NOT_READY";
        if (r->plan.protected_mode && link->fragment_payload_bytes > 199)
            return "INVALID_ARGUMENT";
        const char *const outer[] = {"spec", "budget"};
        const char *const specs[] = {"catalog_id",
                                     "direction",
                                     "source",
                                     "message_count",
                                     "message_bytes",
                                     "source_seed",
                                     "source_artifact_id",
                                     "sample_count",
                                     "security",
                                     "max_duration_ms",
                                     "source_duration_ms",
                                     "instrumentation",
                                     "expected_sha256",
                                     "playback"};
        const char *const budgets[] = {
            "ack_timeout_us",       "reassembly_timeout_us", "drain_us",        "capture_budget_us",
            "processing_budget_us", "playback_budget_us",    "fault_budget_us", "model_version"};
        const cJSON *s = cJSON_GetObjectItemCaseSensitive(args, "spec"),
                    *b = cJSON_GetObjectItemCaseSensitive(args, "budget");
        uint32_t count;
        p->echo = eq(text(s, "source"), "echo");
        p->fixed_source = eq(text(s, "source"), "fixed_rate_encoded");
        p->encoded = p->fixed_source || eq(text(s, "source"), "encoded_source");
        if (p->fixed_source && p->role == (eq(text(s, "direction"), "B_TO_A") ? 2 : 1) &&
            (!r->port.source_worker.reserve || !r->port.source_worker.start || !r->port.source_worker.stop))
            return "MISSING_CAPABILITY";
        if (r->used || r->phase != RF_IDLE || !r->radio->configured || !revision)
            return "INVALID_STATE";
        if (!allowed(args, outer, 2) || !allowed(s, specs, 14) || !allowed(b, budgets, 8) ||
            !literal(s, "catalog_id", p->echo ? "TIME-01" : p->fixed_source ? "VOICE-03" : p->encoded ? "VOICE-02" : "IF-02") ||
            !literal(s, "source", p->echo ? "echo" : p->fixed_source ? "fixed_rate_encoded" : p->encoded ? "encoded_source" : "known_data") ||
            !literal(s, "security", p->protected_mode ? "aes128_gcm" : "none") ||
            !boolean(s, "playback", false) || (!p->fixed_source && !null_value(s, "source_duration_ms")) ||
            (!p->encoded && (!null_value(s, "source_artifact_id") ||
                             !null_value(s, "sample_count") || !null_value(s, "expected_sha256"))) ||
            !integer(s, "message_count", 1, 10000, p->encoded ? 1 : 100, &count) ||
            !integer(s, "message_bytes", 1, UINT32_MAX, 64, &p->bytes) ||
            (!p->encoded && !integer(s, "source_seed", 0, UINT32_MAX, 743, &p->seed)) ||
            !integer(s, "max_duration_ms", 1000, 3600000, 120000, &p->duration_ms))
            return "INVALID_ARGUMENT";
        if (p->bytes > RF_MAX_MESSAGE_BYTES || count != (p->fixed_source ? 20U : 1U))
            return "RESOURCE_LIMIT";
        if (p->echo && (p->bytes > link->fragment_payload_bytes || link->ack_requested || link->max_retries))
            return "INVALID_ARGUMENT";
        if (p->fixed_source && (p->bytes != 1200 || p->duration_ms < 60000 || p->duration_ms > 90000 ||
            !cJSON_GetObjectItemCaseSensitive(s, "source_duration_ms") ||
            !integer(s, "source_duration_ms", 60000, 60000, 0, &count))) return "INVALID_ARGUMENT";
        const char *direction = text(s, "direction");
        if (!direction)
            direction = "A_TO_B";
        if (!eq(direction, "A_TO_B") && !eq(direction, "B_TO_A"))
            return "INVALID_ARGUMENT";
        p->source = eq(direction, "A_TO_B") ? 1 : 2;
        if (p->encoded) {
            const char *id = text(s, "source_artifact_id"), *sha = text(s, "expected_sha256");
            if (!p->protected_mode || !source_text(id, 36) || !source_text(sha, 64) ||
                !cJSON_GetObjectItemCaseSensitive(s, "message_bytes") ||
                !null_value(s, "source_seed") || !cJSON_GetObjectItemCaseSensitive(s, "sample_count") ||
                !integer(s, "sample_count", 1, 24000, 0, &p->sample_count) ||
                p->bytes != ((p->sample_count + 159) / 160) * 8 ||
                (p->fixed_source && p->sample_count != 24000)) return "INVALID_ARGUMENT";
            memcpy(p->source_artifact_id, id, 37);
            memcpy(p->expected_sha256, sha, 65);
            if (p->role == p->source) {
                const artifact_manifest *source = artifact_store_find(r->artifacts, id);
                if (!source) return "ARTIFACT_NOT_FOUND";
                if (source->state != ARTIFACT_COMMITTED) return "INVALID_STATE";
                if (source->in_use) return "BUSY";
                if (!eq(source->format, "codec2_3200_v1") || source->sample_count != p->sample_count ||
                    source->length_bytes != p->bytes || source->frame_count != (p->sample_count + 159) / 160 ||
                    !eq(source->sha256, sha)) return "INVALID_ARGUMENT";
            }
        }
        const cJSON *instrument = cJSON_GetObjectItemCaseSensitive(s, "instrumentation");
        const char *const flags[] = {"packet_events", "crypto_samples", "memory_10hz",
                                     "clock_samples"};
        if (instrument &&
            (!allowed(instrument, flags, 4) || !boolean(instrument, "packet_events", true) ||
             !boolean(instrument, "crypto_samples", false) ||
             !boolean(instrument, "memory_10hz", false) ||
             !boolean(instrument, "clock_samples", false)))
            return "INVALID_ARGUMENT";
        uint32_t unused;
        if (!cJSON_GetObjectItemCaseSensitive(b, "ack_timeout_us") ||
            !cJSON_GetObjectItemCaseSensitive(b, "reassembly_timeout_us") ||
            !cJSON_GetObjectItemCaseSensitive(b, "drain_us") ||
            !cJSON_GetObjectItemCaseSensitive(b, "processing_budget_us"))
            return "INVALID_ARGUMENT";
        if (!integer(b, "ack_timeout_us", 0, 30000000, 0, &p->ack_timeout) ||
            !integer(b, "reassembly_timeout_us", 1, 3600000000U, 0, &p->reassembly) ||
            !integer(b, "drain_us", 0, 3600000000U, 0, &p->drain) ||
            !integer(b, "processing_budget_us", 0, 3600000000U, 0, &p->processing) ||
            !integer(b, "capture_budget_us", 0, 0, 0, &unused) ||
            !integer(b, "playback_budget_us", 0, 0, 0, &unused) ||
            !integer(b, "fault_budget_us", 0, r->port.lab_faults ? 3600000000U : 0, 0, &p->fault_us) ||
            !literal(b, "model_version", "sx126x_lora_v1"))
            return "INVALID_ARGUMENT";
        uint32_t fragments =
            (p->bytes + link->fragment_payload_bytes - 1) / link->fragment_payload_bytes;
        uint32_t last = p->bytes - (fragments - 1) * link->fragment_payload_bytes;
        uint32_t tag_bytes = p->protected_mode ? 16 : 0;
        uint32_t last_air = rf_radio_airtime_us(&r->radio->applied, 40 + last + tag_bytes);
        uint32_t full_air = fragments > 1
                                ? rf_radio_airtime_us(&r->radio->applied,
                                                      40 + link->fragment_payload_bytes + tag_bytes)
                                : last_air;
        uint32_t ack = link->ack_requested
                           ? 100000 + rf_radio_airtime_us(&r->radio->applied, 40 + tag_bytes)
                           : 0;
        uint32_t attempts = 1 + link->max_retries;
        uint64_t horizon =
            link->ack_requested ? (uint64_t)(full_air + ack + link->guard_us) * attempts : 0;
        uint64_t minimum_drain = horizon > 2000000 ? horizon : 2000000;
        uint64_t data = (uint64_t)(fragments - 1) * full_air + last_air;
        uint64_t processing = 10000U * (1U + fragments * attempts + (p->echo ? 1U : 0U)) + (p->encoded ? 5000000U : 0);
        uint64_t lifetime = data * attempts + (p->echo ? data + 20000 : 0) + (uint64_t)fragments * attempts * ack +
                            ((uint64_t)fragments * attempts - 1) * link->guard_us + processing +
                            2000000;
        if (p->ack_timeout != ack || p->drain < minimum_drain || p->processing < processing ||
            (p->fixed_source ? p->reassembly != (uint64_t)p->duration_ms * 1000 :
                p->reassembly < lifetime + p->fault_us || p->reassembly > (uint64_t)p->duration_ms * 1000) ||
            p->drain > (uint64_t)p->duration_ms * 1000)
            return "INVALID_ARGUMENT";
        unsigned faults = rf_faults_count(r->faults);
        if ((faults || p->fault_us) && (p->encoded || p->echo || p->fixed_source)) return "INVALID_ARGUMENT";
        if (r->faults && !p->encoded && !p->echo) {
            rf_message_plan packet;
            if (!rf_message_plan_init(&packet, p->session, 1, 1, p->source, p->source == 1 ? 2 : 1,
                0, p->protected_mode, link->ack_requested, p->bytes, link->fragment_payload_bytes) ||
                !rf_faults_validate(r->faults, &packet, attempts)) return "INVALID_ARGUMENT";
            uint64_t minimum_fault = 0;
            bool barrier = false;
            for (unsigned i = 0; i < faults; i++) {
                rf_fault_view view; rf_faults_view(r->faults, i, &view);
                retained_budget(r, &packet, link, &view.spec, &minimum_fault, &barrier);
            }
            if (p->fault_us < minimum_fault + (barrier ? 1000000 : 0))
                return "INVALID_ARGUMENT";
        }
        unsigned free_slots = 0;
        for (unsigned i = 0; i < ARTIFACT_SLOTS; i++)
            if (!artifact_store_at(r->artifacts, i))
                free_slots++;
        if (!free_slots && !(p->encoded && p->role == p->source))
            return "RESOURCE_LIMIT";
        p->link = *link;
        p->revision = revision;
        snprintf(p->operation, 37, "%s", op);
    }
    else if (action == RF_ARM || action == RF_START)
    {
        const char *const keys[] = {"config_revision"};
        uint32_t requested;
        if (!allowed(args, keys, 1) || !cJSON_GetObjectItemCaseSensitive(args, "config_revision") ||
            !integer(args, "config_revision", 0, UINT32_MAX, 0, &requested))
            return "INVALID_ARGUMENT";
        if (r->phase != (action == RF_ARM ? RF_PREPARED : RF_ARMED) ||
            requested != revision || requested != r->plan.revision ||
            (action == RF_START && !r->sender))
            return "INVALID_STATE";
        if (action == RF_START && r->port.now_us(r->port.context) >= r->arm_deadline)
            return "TIMEOUT";
        if (action == RF_START)
            snprintf(p->operation, 37, "%s", op);
    }
    else if (action == RF_STOP)
    {
        const char *const keys[] = {"reason"};
        const char *reason = text(args, "reason");
        if (!allowed(args, keys, 1) || (!eq(reason, "operator") && !eq(reason, "host_shutdown") &&
                                        !eq(reason, "peer_failure")))
            return "INVALID_ARGUMENT";
        p->reason = eq(reason, "operator")        ? "operator"
                    : eq(reason, "host_shutdown") ? "host_shutdown"
                                                  : "peer_failure";
    }
    else if (action != RF_SOURCE && cJSON_GetArraySize(args))
        return "INVALID_ARGUMENT";
    if (action == RF_SOURCE) {
        if (!r->used || !r->plan.fixed_source) return "INVALID_STATE";
        return source_query(r, args, result);
    }
    if (action == RF_SUMMARY)
    {
        if (!r->used)
            return "INVALID_STATE";
        *result = summary(r);
    }
    else
    {
        *result = object(r);
        if (action == RF_PREPARE || action == RF_START)
        {
            string(r, *result, "operation_id", p->operation);
            string(r, *result, "state", "accepted");
            number(r, *result, "deadline_us",
                   r->port.now_us(r->port.context) + (int64_t)p->duration_ms * 1000);
        }
        else if (action == RF_ARM) {
            string(r, *result, "role", r->sender ? "sender" : "receiver");
            add(r, *result, "receiver_ready", cJSON_CreateBool(!r->sender));
            number(r, *result, "arm_deadline_us", r->port.now_us(r->port.context) + RUN_ARM_WINDOW_US);
        }
        else
        {
            string(r, *result, "state", "idle");
            if (action == RF_OPEN)
                string(r, *result, "session_id", p->session_text);
        }
    }
    if (r->oom)
    {
        cJSON_Delete(*result);
        *result = NULL;
    }
    return NULL;
}
static bool release_buffers(rf_execution *r)
{
    if (r->source_worker) {
        if (!eq(r->stop_reason, "completed")) encoded_queue_request_stop(r->queue);
        if (!r->port.source_worker.stop(r->port.source_worker.context, r->source_worker)) {
            r->source_cleanup_failed = true;
            return false;
        }
        r->source_worker = NULL;
        r->source_cleanup_failed = false;
    }
    if (r->queue && r->active_message) {
        encoded_queue_complete(r->queue, r->active_message, SOURCE_DISCARDED);
        r->active_message = 0;
    }
    if (r->port.before_release) r->port.before_release(r->port.context);
    if (r->queue) encoded_queue_retire_payload(r->queue);
    if (r->echo) {
        rf_echo_abort(r->echo, r->stop_reason ? r->stop_reason : "prepare_failed");
        rf_echo_snapshot(r->echo, &r->echo_status);
        rf_echo_destroy(r->echo);
        r->echo = NULL;
    }
    rf_ack_destroy(r->acknowledgments);
    r->acknowledgments = NULL;
    r->ack_pending = r->ack_transmitting = false;
    rf_sender_destroy(r->transmitter);
    r->transmitter = NULL;
    rf_reassembly_destroy(r->receiver);
    r->receiver = NULL;
    if (r->source_borrowed)
        artifact_store_release(r->artifacts, r->plan.source_artifact_id);
    if (r->generated) {
        memset(r->generated, 0, r->plan.bytes);
        r->port.release(r->port.context, r->generated);
    }
    r->source_borrowed = false;
    r->generated = r->recovered_output = NULL;
    r->payload = NULL;
    return true;
}
static bool prepare_failed(rf_execution *r)
{
    rf_faults_unprepare(r->faults);
    if (!release_buffers(r)) { r->used = true; return false; }
    encoded_queue_destroy(r->queue); r->queue = NULL;
    if (r->artifact_reserved)
        artifact_store_delete(r->artifacts, r->artifact_id);
    r->artifact_reserved = false;
    r->used = false;
    r->phase = RF_IDLE;
    return false;
}
static bool publish_bytes(rf_execution *r, const void *bytes)
{
    const uint8_t *source = bytes;
    if (r->plan.encoded) {
        if (!r->recovered_output) return false;
        memcpy(r->recovered_output, bytes, r->plan.bytes);
        if (artifact_store_encode_finish(r->artifacts, r->artifact_id, r->port.hash, r->port.context) != ARTIFACT_OK)
            return false;
        const artifact_manifest *output = artifact_store_find(r->artifacts, r->artifact_id);
        if (!output || !eq(output->sha256, r->plan.expected_sha256)) {
            artifact_store_delete(r->artifacts, r->artifact_id);
            return false;
        }
        return true;
    }
    for (size_t offset = 0; offset < r->plan.bytes;)
    {
        size_t size = r->plan.bytes - offset;
        if (size > ARTIFACT_CHUNK_BYTES)
            size = ARTIFACT_CHUNK_BYTES;
        if (artifact_store_put(r->artifacts, r->artifact_id, offset, source + offset, size,
                               chunk_crc32(source + offset, size)) != ARTIFACT_OK)
            return false;
        offset += size;
    }
    if (artifact_store_prepare_commit(r->artifacts, r->artifact_id, r->port.hash,
                                      r->port.context) != ARTIFACT_OK)
        return false;
    artifact_store_accept_commit(r->artifacts, r->artifact_id);
    return true;
}
static void sender_counts(rf_execution *r, const rf_sender_status *s)
{
    r->attempts += s->attempts - r->frame_attempts;
    r->frame_attempts = s->attempts;
}
static size_t encode_data(void *context, uint16_t fragment, uint8_t frame[255])
{
    rf_execution *r = context;
    size_t length = 0;
    if (r->plan.protected_mode)
    {
        uint8_t header[40];
        if (!rf_message_header(&r->fragments, fragment, header))
            return 0;
        size_t body_bytes = ((unsigned)header[32] << 8) | header[33];
        if (rf_secure_seal(r->security, header,
                           r->payload + (uint32_t)fragment * r->fragments.fragment_bytes,
                           body_bytes, frame, 255, &length) != RF_CRYPTO_OK)
            return 0;
    }
    else
        length =
            rf_message_fragment(&r->fragments, fragment, r->payload, r->plan.bytes, frame);
    return length;
}

static bool transmit(rf_execution *r)
{
    uint8_t frame[255];
    const uint8_t *wire = frame;
    size_t length = 0;
    r->wire_fragment = r->tx_fragment;
    rf_fault_match schedule = rf_faults_order(r->faults, r->tx_fragment, encode_data, r,
        r->port.now_us(r->port.context), &wire, &length, &r->wire_fragment);
    if (schedule == RF_FAULT_OBSERVATION_FAILED) return false;
    if (schedule == RF_FAULT_NO_MATCH)
        length = encode_data(r, r->wire_fragment, frame);
    if (!length || !rf_sender_begin(r->transmitter, wire, length,
                                    r->plan.link.fragment_payload_bytes, r->plan.link.max_retries,
                                    r->plan.link.guard_us, 20000, 80000, r->deadline))
        return false;
    r->frame_attempts = r->frame_originals = 0;
    r->next_tx = -1;
    rf_sender_poll(r->transmitter, NULL);
    rf_sender_status status;
    rf_sender_snapshot(r->transmitter, &status);
    sender_counts(r, &status);
    return status.state == RF_SENDER_TX;
}
bool rf_execution_apply(rf_execution *r, const rf_plan *p)
{
    if (p->action == RF_SUMMARY || p->action == RF_SOURCE)
        return true;
    if (p->action == RF_OPEN)
    {
        r->plan = *p;
        r->radio_cleanup_failed = r->key_cleanup_failed = r->source_cleanup_failed = false;
        r->plan.provision_keys = NULL;
        r->used = false;
        r->finished = false;
        r->fault_pending_valid = r->injected_tx = false;
        if (r->port.lab_faults) {
            r->faults = rf_faults_create((rf_packet_port){r->port.context, r->port.allocate, r->port.release, r->port.hash}, p->session, p->role);
            if (!r->faults) return false;
        }
        if (p->protected_mode)
        {
            const char *tx = text(p->provision_keys, "tx_key_hex"),
                       *rx = text(p->provision_keys, "rx_key_hex");
            if (!key_text(tx) || !key_text(rx))
                return false;
            uint8_t tx_key[16], rx_key[16];
            decode_key(tx, tx_key);
            decode_key(rx, rx_key);
            rf_crypto_status status =
                rf_secure_create(p->session, p->role, tx_key, rx_key, &r->security);
            for (unsigned i = 0; i < 16; i++)
            {
                ((volatile uint8_t *)tx_key)[i] = 0;
                ((volatile uint8_t *)rx_key)[i] = 0;
            }
            if (status != RF_CRYPTO_OK) { rf_faults_destroy(r->faults); r->faults = NULL; }
            return status == RF_CRYPTO_OK;
        }
        return true;
    }
    if (p->action == RF_FAULT_STATUS) return true;
    if (p->action == RF_FAULT_SET) {
        rf_fault_spec specs[RF_FAULT_BATCH]; size_t count; bool replace;
        return rf_fault_json_parse(p->fault_arguments, specs, &count, &replace) &&
            rf_faults_configure(r->faults, specs, count, replace);
    }
    if (p->action == RF_FAULT_FIRE) {
        const char *id = text(p->fault_arguments, "injection_id"); size_t bytes;
        const uint8_t *wire = rf_faults_replay(r->faults, id, &bytes);
        if (!wire || !fire_window(r)) return false;
        for (unsigned i = 0; i < rf_faults_count(r->faults); i++) {
            rf_fault_view view; rf_faults_view(r->faults, i, &view);
            if (eq(view.spec.id, id)) r->replay_view = view;
        }
        node_radio_reference ref = {p->session, r->replay_view.sequence, r->replay_view.spec.message,
            r->replay_view.spec.fragment, r->replay_view.spec.attempt};
        uint32_t timeout = rf_radio_airtime_us(&r->radio->applied, bytes) + 80000;
        if (r->radio->operation || r->radio->event_pending ||
            r->drain_deadline - r->port.now_us(r->port.context) < timeout ||
            !node_radio_tx(r->radio, wire, bytes, &ref, timeout)) return false;
        r->injected_tx = true;
        snprintf(r->replay_id, sizeof(r->replay_id), "%s", id);
        return rf_faults_fired(r->faults, id, r->port.now_us(r->port.context));
    }
    if (p->action == RF_STOP)
        return rf_execution_abort(r, p->reason, false);
    if (p->action == RF_CLOSE)
        return rf_execution_abort(r, "operator", true);
    if (p->action == RF_PREPARE)
    {
        r->plan = *p;
        r->echo_reply_hex[0] = 0;
        r->echo_status = (rf_echo_status){.requester = p->role == p->source,
            .tx_command_us = -1, .accepted_us = -1, .reason = "not_started"};
        r->sender = p->role == p->source;
        r->observations = r->accepted = r->duplicates = r->attempts = r->delivered = 0;
        r->originals = r->active_message = r->received_message = r->delivered_bitmap = r->source_finished_messages = r->received_messages = 0;
        r->archive_sha[0] = 0;
        r->tx_fragment = r->wire_fragment = 0;
        r->duplicate_due = -1;
        r->next_tx = r->first_fragment = -1;
        r->missing_count = r->missing_parts = r->missing_part = 0;
        r->missing_cursor = 0;
        r->failure_result_reported = r->missing_evidence_incomplete = false;
        r->artifact_id[0] = 0;
        r->artifact_reserved = false;
        r->ack_pending = r->ack_transmitting = false;
        if (p->encoded && r->sender) {
            const void *source = NULL;
            size_t size = 0;
            if (artifact_store_acquire(r->artifacts, p->source_artifact_id, &source, &size) != ARTIFACT_OK)
                return false;
            r->source_borrowed = true;
            r->payload = source;
            if (size != p->bytes) { return prepare_failed(r); }
        } else if (!p->encoded) {
            r->generated = r->port.allocate(r->port.context, p->bytes);
            r->payload = r->generated;
            if (!r->payload) return prepare_failed(r);
        }
        r->first_tx = r->last_tx = r->first_rx = r->last_rx = -1;
        r->finished = r->failed = r->started = false;
        r->stop_reason = NULL;
        r->drops_start = r->port.drops(r->port.context);
        uint8_t digest[32];
        if (!rf_message_plan_init(&r->fragments, p->session, 1, 1, p->source,
                                  p->source == 1 ? 2 : 1, p->encoded ? 1 : 0, p->protected_mode,
                                  p->link.ack_requested, p->bytes,
                                  p->link.fragment_payload_bytes) ||
            (!p->encoded && !rf_known_data(r->port.hash, r->port.context, p->seed, 1, r->generated, p->bytes)) ||
            ((!p->encoded || r->sender) && !r->port.hash(r->port.context, r->payload, p->bytes, digest)))
        {
            return prepare_failed(r);
        }
        if (p->encoded) {
            uint8_t expected[32];
            decode_hash(p->expected_sha256, expected);
            if (r->sender && memcmp(digest, expected, 32)) { return prepare_failed(r); }
            memcpy(digest, expected, 32);
        }
        if (r->sender && p->protected_mode && !p->fixed_source)
        {
            uint32_t first = 0;
            if (rf_secure_reserve(r->security, r->fragments.fragment_count, &first) != RF_CRYPTO_OK)
            {
                return prepare_failed(r);
            }
            r->fragments.first_sequence = first;
        }
        memcpy(r->expected_hash, digest, 32);
        hex(digest, r->sha_hex);
        if (p->encoded && r->sender) memcpy(r->artifact_id, p->source_artifact_id, 37);
        else {
            uuid(r, r->artifact_id);
            artifact_status status;
            if (p->fixed_source) {
                void *output = NULL;
                status = artifact_store_source_archive_begin(r->artifacts, p->owner, r->artifact_id, &output);
                r->recovered_output = output;
            } else if (p->encoded) {
                void *output = NULL;
                status = artifact_store_recover_encoded_begin(r->artifacts, p->owner, r->artifact_id,
                    p->source_artifact_id, p->sample_count, p->expected_sha256, &output);
                r->recovered_output = output;
            } else {
                artifact_spec spec = {r->artifact_id, r->sender ? "source" : "recovered", r->sha_hex, "known_data", p->bytes};
                status = artifact_store_begin(r->artifacts, p->owner, &spec);
            }
            if (status != ARTIFACT_OK) { return prepare_failed(r); }
            r->artifact_reserved = true;
        }
        rf_packet_port port = {r->port.context, r->port.allocate, r->port.release, r->port.hash};
        if (r->faults && !p->encoded && !p->echo &&
            !rf_faults_prepare(r->faults, &r->fragments, 1 + p->link.max_retries)) return prepare_failed(r);
        if (p->echo)
        {
            r->echo = rf_echo_create((rf_echo_port){port, r->port.now_us, r->radio, r->security},
                &r->fragments, r->payload, r->sender, p->drain);
            if (!r->echo) return prepare_failed(r);
        }
        else if (r->sender)
        {
            r->transmitter = rf_sender_create(port, r->radio);
            if (!r->transmitter ||
                (p->protected_mode && !rf_sender_security(r->transmitter, r->security)))
            {
                return prepare_failed(r);
            }
        }
        else
        {
            r->receiver = rf_reassembly_create(port, p->session, p->source, p->role,
                                               p->link.fragment_payload_bytes);
            int64_t prepared_at = r->port.now_us(r->port.context);
            if (!r->receiver || !rf_reassembly_begin(r->receiver, 1, p->encoded ? 1 : 0,
                (p->protected_mode ? 1 : 0) | (p->link.ack_requested ? 2 : 0),
                p->bytes, r->expected_hash, prepared_at,
                prepared_at + (int64_t)p->duration_ms * 1000))
            {
                return prepare_failed(r);
            }
            if (p->fixed_source) rf_reassembly_stream(r->receiver);
            if (p->link.ack_requested && !p->protected_mode)
            {
                r->acknowledgments =
                    rf_ack_create(port, p->session, p->role, p->source,
                                  p->link.fragment_payload_bytes, 1, 20000, p->drain);
                if (!r->acknowledgments)
                {
                    return prepare_failed(r);
                }
            }
        }
        if (p->fixed_source && r->sender) {
            r->queue = encoded_queue_create((encoded_source_memory){r->port.context, r->port.allocate, r->port.release},
                r->payload, p->bytes, p->duration_ms * 1000U - SOURCE_DURATION_US);
            if (!r->queue) return prepare_failed(r);
            r->source_worker = r->port.source_worker.reserve(r->port.source_worker.context, r->queue);
            if (!r->source_worker) return prepare_failed(r);
        }
        if (r->sender && r->faults && !p->encoded && !p->echo &&
            !rf_sender_faults(r->transmitter, r->faults)) return prepare_failed(r);
        if (r->sender && !p->encoded && !publish_bytes(r, r->payload))
            return prepare_failed(r);
        r->used = true;
        r->deadline = r->port.now_us(r->port.context) + (int64_t)p->duration_ms * 1000;
        r->phase = RF_PREPARING;
        return true;
    }
    if (p->action == RF_ARM)
    {
        int64_t now = r->port.now_us(r->port.context);
        r->arm_deadline = now + RUN_ARM_WINDOW_US;
        if (r->sender) {
            r->phase = RF_ARMED;
            return true; // Arming reserves intent; no radio command or nonce use.
        }
        int64_t lifetime = p->echo || p->fixed_source ? (int64_t)p->duration_ms * 1000 : p->reassembly < (uint64_t)p->duration_ms * 1000
                               ? p->reassembly
                               : (int64_t)p->duration_ms * 1000;
        lifetime += RUN_ARM_WINDOW_US; // Receiver cannot observe the peer's start acceptance.
        if (p->echo ? !rf_echo_arm(r->echo, now + lifetime) :
            !rf_reassembly_arm(r->receiver, now, now + lifetime))
            return false;
        r->receive_deadline = now + lifetime;
        uint32_t slice = lifetime > 30000000 ? 30000000 : lifetime;
        if ((!p->echo && !node_radio_rx(r->radio, 255, slice)) || r->radio->operation != 2)
        {
            rf_execution_abort(r, "error", true);
            return false;
        }
        r->deadline = r->arm_deadline + (int64_t)p->duration_ms * 1000;
        r->phase = RF_ARMED;
        r->started = true;
        return true;
    }
    if (p->action == RF_START)
    {
        r->plan = *p;
        r->deadline = r->port.now_us(r->port.context) + (int64_t)p->duration_ms * 1000;
        if (p->echo ? !rf_echo_start(r->echo, r->deadline) : p->fixed_source ? !r->port.source_worker.start(r->port.source_worker.context, r->source_worker,
                r->port.now_us(r->port.context)) : !transmit(r)) {
            rf_execution_abort(r, "error", true);
            return false;
        }
        r->started = true;
        r->phase = RF_RUNNING;
        return true;
    }
    return false;
}
static void finalize(rf_execution *r, const char *reason, bool failed)
{
    bool operation_active = r->phase == RF_PREPARING || (r->sender && (r->phase == RF_RUNNING || r->phase == RF_DRAINING));
    r->phase = RF_IDLE;
    r->stop_reason = reason;
    r->finished = true;
    r->failed = failed;
    rf_faults_finish(r->faults);
    r->injected_tx = false;
    if (r->radio && (r->radio->operation || r->radio->event_pending))
    {
        if (!node_radio_stop(r->radio)) r->radio_cleanup_failed = true;
        node_radio_event ignored;
        node_radio_poll(r->radio, &ignored);
    }
    if (r->plan.fixed_source && !r->sender && r->recovered_output) {
        if (artifact_store_source_archive_finish(r->artifacts, r->artifact_id, r->port.hash, r->port.context) == ARTIFACT_OK) {
            const artifact_manifest *m = artifact_store_find(r->artifacts, r->artifact_id);
            if (m) memcpy(r->archive_sha, m->sha256, 65);
        } else failed = r->failed = true;
    }
    if (!release_buffers(r)) failed = r->failed = true;
    if (failed && !r->plan.fixed_source && !r->sender && !r->delivered)
        artifact_store_delete(r->artifacts, r->artifact_id);
    send(r, "run.summary", summary(r));
    if (operation_active)
    {
        cJSON *o = object(r);
        string(r, o, "kind", r->plan.echo ? "echo_request" : r->plan.encoded ? "encoded_voice_tx" : "known_data_tx");
        operation(r, !failed, failed ? (cJSON_Delete(o), (cJSON *)NULL) : o);
    }
    state(r);
}
static void finish(rf_execution *r, const char *reason, bool failed)
{
    if (r->phase == RF_REPORTING)
        return;
    if (failed && !r->plan.fixed_source && !r->sender && r->started && !r->delivered && r->receiver)
    {
        if (r->radio->operation || r->radio->event_pending)
        {
            if (!node_radio_stop(r->radio)) r->radio_cleanup_failed = true;
            node_radio_event ignored;
            node_radio_poll(r->radio, &ignored);
        }
        r->stop_reason = reason;
        r->failed = r->finished = true;
        uint16_t missing[64];
        unsigned cursor = 0;
        size_t n;
        r->missing_count = 0;
        while ((n = rf_reassembly_missing(r->receiver, cursor, missing, 64)))
        {
            r->missing_count += n;
            cursor = missing[n - 1] + 1;
        }
        r->missing_parts = (r->missing_count + 63) / 64;
        r->missing_part = r->missing_cursor = 0;
        r->failure_result_reported = false;
        r->phase = RF_REPORTING;
        return;
    }
    finalize(r, reason, failed);
}
static void report_failure(rf_execution *r)
{
    if (r->missing_part < r->missing_parts)
    {
        if (!r->port.room(r->port.context, 1))
            return;
        uint16_t missing[64];
        size_t n = rf_reassembly_missing(r->receiver, r->missing_cursor, missing, 64);
        cJSON *o = object(r), *ranges = cJSON_CreateArray();
        number(r, o, "message_id", r->plan.fixed_source ? (r->sender ? r->active_message : r->received_message) : 1);
        number(r, o, "part_index", r->missing_part);
        number(r, o, "part_count", r->missing_parts);
        for (size_t i = 0; i < n; i++)
        {
            int pair[] = {missing[i], missing[i]};
            cJSON *range = cJSON_CreateIntArray(pair, 2);
            if (!range || !ranges || !cJSON_AddItemToArray(ranges, range))
            {
                cJSON_Delete(range);
                r->oom = true;
            }
        }
        add(r, o, "ranges", ranges);
        if (send(r, "message.missing", o))
        {
            r->missing_cursor = missing[n - 1] + 1;
            r->missing_part++;
        }
        return;
    }
    if (!r->failure_result_reported)
    {
        if (!r->port.room(r->port.context, 1))
            return;
        cJSON *o = object(r);
        number(r, o, "message_id", r->plan.fixed_source ? (r->sender ? r->active_message : r->received_message) : 1);
        string(r, o, "status", "failed");
        number(r, o, "message_bytes", r->plan.bytes);
        string(r, o, "sha256", NULL);
        number(r, o, "fragment_count", r->fragments.fragment_count);
        number(r, o, "missing_count", r->missing_count);
        number(r, o, "missing_parts", r->missing_parts);
        if (r->first_fragment >= 0)
            number(r, o, "first_fragment_us", r->first_fragment);
        else
            string(r, o, "first_fragment_us", NULL);
        string(r, o, "complete_us", NULL);
        if (send(r, "message.result", o))
            r->failure_result_reported = true;
        return;
    }
    if (r->port.room(r->port.context, 2))
        finalize(r, r->stop_reason, true);
}
bool rf_execution_abort(rf_execution *r, const char *reason, bool close)
{
    rf_faults_disable(r->faults);
    r->injected_tx = false;
    bool ok = true;
    if (r->radio && (r->radio->operation || r->radio->event_pending))
    {
        ok = node_radio_stop(r->radio);
        if (!ok) r->radio_cleanup_failed = true;
        node_radio_event ignored;
        node_radio_poll(r->radio, &ignored);
    }
    if (r->phase == RF_REPORTING)
    {
        r->missing_evidence_incomplete =
            r->missing_part < r->missing_parts || !r->failure_result_reported;
        finalize(r, r->stop_reason ? r->stop_reason : reason, true);
    }
    else if (r->phase != RF_IDLE)
        finish(r, reason, true);
    if (r->phase == RF_REPORTING)
    {
        r->missing_evidence_incomplete = true;
        finalize(r, r->stop_reason ? r->stop_reason : reason, true);
    }
    if (rf_secure_close(&r->security) != RF_CRYPTO_OK) {
        r->key_cleanup_failed = true;
        ok = false;
    }
    if (close)
    {
        if (!release_buffers(r)) return false;
        encoded_queue_destroy(r->queue); r->queue = NULL;
        rf_faults_destroy(r->faults); r->faults = NULL;
        r->fault_pending_valid = false;
        artifact_store_release_owner(r->artifacts, r->plan.owner);
        if (!r->security)
        {
            r->plan.session = 0;
            r->plan.protected_mode = false;
        }
        r->used = false;
        r->phase = RF_IDLE;
    }
    return ok;
}
static void rejected_at(rf_execution *r, const char *reason, const rf_data_view *header,
                        int64_t rx_done)
{
    cJSON *o = object(r);
    if (header && r->port.lab_faults) {
        char session[17];
        snprintf(session, sizeof(session), "%016" PRIx64, header->session);
        string(r, o, "session_id", session);
        string(r, o, "source_role", header->source == 1 ? "A" : "B");
        number(r, o, "frame_seq", header->frame_sequence);
        number(r, o, "message_id", header->message_id);
        number(r, o, "fragment_index", header->fragment_index);
    } else {
        string(r, o, "session_id", NULL);
        string(r, o, "source_role", NULL);
        string(r, o, "frame_seq", NULL);
        string(r, o, "message_id", NULL);
        string(r, o, "fragment_index", NULL);
    }
    if (rx_done >= 0)
        number(r, o, "rx_done_us", rx_done);
    string(r, o, "stage",
           eq(reason, "wrong_session") || eq(reason, "wrong_source") ? "session"
           : eq(reason, "content_mismatch") || eq(reason, "wrong_reference") || eq(reason, "wrong_message") ? "reassembly"
           : eq(reason, "authentication_failed") || eq(reason, "protection_mismatch") ||
                   eq(reason, "crypto_unavailable")
               ? "authentication"
           : eq(reason, "replay") || eq(reason, "too_old") || eq(reason, "duplicate") ? "replay"
                                                           : "framing");
    string(r, o, "reason", reason);
    string(r, o, "related_injection_id", NULL);
    send(r, "rx.rejected", o);
}
static void rejected(rf_execution *r, const char *reason)
{
    rejected_at(r, reason, NULL, -1);
}
static void wire_digest(rf_execution *r, cJSON *o, const uint8_t *digest)
{
    if (!digest) return;
    char digest_hex[65];
    hex(digest, digest_hex);
    string(r, o, "wire_sha256", digest_hex);
}
static uint32_t word(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static void tx_observation(rf_execution *r, const node_radio_event *event, const char *kind)
{
    cJSON *o = object(r);
    string(r, o, "session_id", r->plan.session_text);
    number(r, o, "frame_seq", event->reference.frame_seq);
    number(r, o, "message_id", event->reference.message_id);
    number(r, o, "fragment_index", event->reference.fragment_index);
    number(r, o, "attempt_index", event->reference.attempt_index);
    string(r, o, "frame_type", kind);
    number(r, o, "frame_bytes", event->frame_bytes);
    if (event->command_us >= 0)
        number(r, o, "tx_command_us", event->command_us);
    else
        string(r, o, "tx_command_us", NULL);
    if (event->done_us >= 0)
        number(r, o, "tx_done_us", event->done_us);
    else
        string(r, o, "tx_done_us", NULL);
    string(r, o, "status", event->status == RADIO_DONE ? "completed" : "failed");
    if (eq(kind, "data")) wire_digest(r, o, rf_sender_wire_digest(r->transmitter));
    send(r, "tx.attempt", o);
}
static bool resume_receive(rf_execution *r)
{
    int64_t now = r->port.now_us(r->port.context);
    int64_t until = !r->plan.fixed_source && r->delivered ? r->drain_deadline : r->receive_deadline;
    int64_t remaining = until - now;
    if (remaining <= 0 && !r->plan.fixed_source && r->delivered && !r->ack_pending && !r->ack_transmitting)
    {
        finish(r, "completed", false); // The completed drain can expire between timer reads.
        return true;
    }
    return remaining > 0 &&
           node_radio_rx(r->radio, 255, remaining > 30000000 ? 30000000 : remaining);
}
static bool receiver_ack_work(rf_execution *r)
{
    int64_t now = r->port.now_us(r->port.context);
    if (!r->plan.fixed_source && r->delivered && now >= r->drain_deadline)
    {
        finish(r, r->ack_pending || r->ack_transmitting ? "timeout" : "completed",
               r->ack_pending || r->ack_transmitting);
        return true;
    }
    if (r->ack_transmitting)
    {
        node_radio_event event;
        if (!node_radio_poll(r->radio, &event))
            return true;
        tx_observation(r, &event, "ack");
        r->ack_transmitting = false;
        if (event.status != RADIO_DONE || !resume_receive(r))
            finish(r, "error", true);
        return true;
    }
    if (!r->ack_pending)
        return false;
    uint8_t frame[56];
    size_t length = 0;
    if (r->plan.protected_mode)
    {
        if (now < r->protected_ack_due)
            return true;
        uint8_t header[40];
        memcpy(header, r->protected_ack_header, sizeof(header));
        header[3] = 2;
        header[4] = 1;
        header[5] = r->plan.role;
        header[6] = r->plan.source;
        memcpy(header + 34, header + 16, 4);
        uint32_t sequence = 0;
        if (rf_secure_reserve(r->security, 1, &sequence) != RF_CRYPTO_OK)
        {
            finish(r, "error", true);
            return true;
        }
        header[16] = sequence >> 24;
        header[17] = sequence >> 16;
        header[18] = sequence >> 8;
        header[19] = sequence;
        header[32] = header[33] = 0;
        if (rf_secure_seal(r->security, header, NULL, 0, frame, sizeof(frame), &length) !=
            RF_CRYPTO_OK)
        {
            finish(r, "error", true);
            return true;
        }
    }
    else
        length = rf_ack_take(r->acknowledgments, now, frame);
    if (!length)
    {
        if (now >= r->deadline)
            finish(r, "timeout", true);
        return true;
    }
    node_radio_reference reference = {r->plan.session, word(frame + 16), word(frame + 20),
                                      ((uint16_t)frame[24] << 8) | frame[25], 1};
    uint32_t timeout = rf_radio_airtime_us(&r->radio->applied, length) + 80000;
    if (!node_radio_tx(r->radio, frame, length, &reference, timeout))
        finish(r, "error", true);
    else
    {
        r->attempts++;
        r->ack_transmitting = true;
        r->ack_pending = false;
    }
    return true;
}
static void received_ack(rf_execution *r, const node_radio_event *event)
{
    if (!event->signal_valid)
        return;
    uint8_t data[40];
    bool decoded = event->crc_ok && event->frame_bytes == (r->plan.protected_mode ? 56 : 40) &&
                   rf_message_header(&r->fragments, r->wire_fragment, data) &&
                   rf_ack_header_matches(event->bytes, data);
    r->observations++;
    if (r->first_rx < 0)
        r->first_rx = event->done_us;
    r->last_rx = event->done_us;
    cJSON *o = object(r);
    string(r, o, "session_id", decoded ? r->plan.session_text : NULL);
    string(r, o, "source_role", decoded ? (r->plan.source == 1 ? "B" : "A") : NULL);
    if (decoded)
    {
        number(r, o, "frame_seq", word(event->bytes + 16));
        number(r, o, "message_id", r->plan.fixed_source ? (r->sender ? r->active_message : r->received_message) : 1);
        number(r, o, "fragment_index", r->wire_fragment);
    }
    else
    {
        string(r, o, "frame_seq", NULL);
        string(r, o, "message_id", NULL);
        string(r, o, "fragment_index", NULL);
    }
    string(r, o, "frame_type", decoded ? "ack" : NULL);
    number(r, o, "frame_bytes", event->frame_bytes);
    number(r, o, "rx_done_us", event->done_us);
    add(r, o, "rssi_dbm", cJSON_CreateNumber(event->rssi_dbm));
    add(r, o, "snr_db", cJSON_CreateNumber(event->snr_db));
    add(r, o, "crc_ok", cJSON_CreateBool(event->crc_ok));
    send(r, "rx.frame", o);
}
typedef struct
{
    rf_execution *execution;
    rf_data_view *header;
    const node_radio_event *event;
    rf_reassembly_result insertion;
    rf_acceptance accepted;
    rf_fault_match fault;
} protected_insertion;

static rf_fault_match receiver_fault(rf_execution *r, rf_fault_action action, const rf_data_view *h,
                                     const node_radio_event *event)
{
    if (!r->faults) return RF_FAULT_NO_MATCH;
    return rf_faults_receive(r->faults, action, h, event->bytes, event->frame_bytes,
                             event->done_us, r->port.now_us(r->port.context));
}
static bool insert_protected(void *context, const uint8_t header[40], const uint8_t *body,
                             size_t bytes)
{
    protected_insertion *call = context;
    rf_execution *r = call->execution;
    rf_data_view *h = call->header;
    if (h->session != r->plan.session)
        call->accepted = RF_WRONG_SESSION;
    else if (h->source != r->plan.source || h->destination != r->plan.role)
        call->accepted = RF_WRONG_ROLE;
    else if ((r->plan.fixed_source ? (h->message_id < 1 || h->message_id > 20 || h->message_id < r->received_message) : h->message_id != 1) || h->message_bytes != r->plan.bytes || h->content != (r->plan.encoded ? 1 : 0) ||
             h->fragment_count != r->fragments.fragment_count ||
             h->flags != (unsigned)(1 | (r->plan.link.ack_requested ? 2 : 0)) ||
             bytes != h->body_bytes)
        call->accepted = RF_WRONG_MESSAGE;
    else if (!r->plan.encoded && memcmp(body, r->payload + (uint32_t)h->fragment_index * r->fragments.fragment_bytes,
                    bytes))
        call->accepted = RF_CONTENT_MISMATCH;
    else
    {
        call->fault = receiver_fault(r, RF_FAULT_DROP, h, call->event);
        if (call->fault != RF_FAULT_NO_MATCH) return false;
        int64_t received = call->event->done_us;
        if (r->plan.fixed_source && h->message_id > r->received_message) {
            if (r->received_message && !rf_reassembly_next(r->receiver, h->message_id,
                received, r->receive_deadline)) { call->accepted = RF_INTERNAL_ERROR; return false; }
            if (!r->received_message && h->message_id != 1 && !rf_reassembly_next(r->receiver, h->message_id,
                received, r->receive_deadline)) { call->accepted = RF_INTERNAL_ERROR; return false; }
            r->received_message = h->message_id;
            r->received_messages++;
            r->first_fragment = -1;
        }
        call->insertion =
            rf_reassembly_accept_authenticated(r->receiver, header, body, bytes, received);
        if (call->insertion == RF_REASSEMBLY_ACCEPTED || call->insertion == RF_REASSEMBLY_COMPLETE)
        {
            call->accepted = RF_DELIVERED;
            return true;
        }
        call->accepted =
            call->insertion == RF_REASSEMBLY_DUPLICATE ? RF_WRONG_MESSAGE :
            r->plan.fixed_source && call->insertion == RF_REASSEMBLY_HASH_FAILED ? RF_CONTENT_MISMATCH : RF_INTERNAL_ERROR;
    }
    return false;
}
static bool continue_source_after_failure(rf_execution *r, const rf_sender_status *status)
{
    if (!r->plan.fixed_source || !eq(status->reason, "retry_exhausted") ||
        !r->radio->available || r->radio->operation || r->radio->event_pending) return false;
    encoded_queue_complete(r->queue, r->active_message, SOURCE_FAILED);
    r->active_message = 0;
    r->source_finished_messages++;
    r->next_tx = -1;
    return true;
}
static void echo_work(rf_execution *r)
{
    rf_echo_event event;
    rf_echo_poll(r->echo, &event);
    rf_echo_snapshot(r->echo, &r->echo_status);
    rf_echo_status *status = &r->echo_status;
    size_t reply_bytes;
    const uint8_t *reply = rf_echo_reply(r->echo, &reply_bytes);
    if (reply) {
        const char *digits = "0123456789abcdef";
        for (size_t i = 0; i < reply_bytes; i++) {
            r->echo_reply_hex[2 * i] = digits[reply[i] >> 4];
            r->echo_reply_hex[2 * i + 1] = digits[reply[i] & 15];
        }
        r->echo_reply_hex[2 * reply_bytes] = 0;
    }
    r->attempts = r->sender ? status->attempts : 0;
    if (event.observed && event.radio.kind == RADIO_EVENT_TX)
    {
        tx_observation(r, &event.radio, r->sender ? "echo_request" : "echo_reply");
        if (r->first_tx < 0) r->first_tx = event.radio.command_us;
        r->last_tx = event.radio.done_us;
        if (r->sender && event.radio.status == RADIO_DONE) r->originals = 1;
    }
    if (event.observed && event.radio.kind == RADIO_EVENT_RX && event.radio.signal_valid)
    {
        r->observations++;
        if (r->first_rx < 0) r->first_rx = event.radio.done_us;
        r->last_rx = event.radio.done_us;
        cJSON *o = object(r);
        char session[17];
        snprintf(session, sizeof(session), "%016llx", (unsigned long long)event.header.session);
        string(r, o, "session_id", event.decoded ? session : NULL);
        string(r, o, "source_role", event.decoded ? event.header.source == 1 ? "A" : "B" : NULL);
        if (event.decoded) {
            number(r, o, "frame_seq", event.header.sequence);
            number(r, o, "message_id", event.header.message);
            number(r, o, "fragment_index", 0);
        } else {
            string(r, o, "frame_seq", NULL);
            string(r, o, "message_id", NULL);
            string(r, o, "fragment_index", NULL);
        }
        string(r, o, "frame_type", event.decoded ? event.header.type == 3 ? "echo_request" : "echo_reply" : NULL);
        number(r, o, "frame_bytes", event.radio.frame_bytes);
        number(r, o, "rx_done_us", event.radio.done_us);
        number(r, o, "rssi_dbm", event.radio.rssi_dbm);
        number(r, o, "snr_db", event.radio.snr_db);
        add(r, o, "crc_ok", cJSON_CreateBool(event.radio.crc_ok));
        send(r, "rx.frame", o);
    }
    if (event.rejection) {
        if (eq(event.rejection, "duplicate")) r->duplicates++;
        rejected(r, event.rejection);
    }
    if (event.accepted)
    {
        r->accepted++;
        cJSON *o = object(r);
        string(r, o, "session_id", r->plan.session_text);
        string(r, o, "source_role", event.header.source == 1 ? "A" : "B");
        number(r, o, "frame_seq", event.header.sequence);
        number(r, o, "message_id", event.header.message);
        number(r, o, "fragment_index", 0);
        number(r, o, "payload_bytes", r->plan.bytes);
        number(r, o, "accepted_us", event.accepted_us);
        send(r, "rx.accepted", o);
        if (!r->sender && !r->delivered)
        {
            if (!publish_bytes(r, r->payload)) { finish(r, "error", true); return; }
            r->delivered = 1;
            cJSON *message = object(r);
            number(r, message, "message_id", 1);
            string(r, message, "status", "delivered");
            number(r, message, "message_bytes", r->plan.bytes);
            string(r, message, "sha256", r->sha_hex);
            number(r, message, "fragment_count", 1);
            number(r, message, "missing_count", 0);
            number(r, message, "missing_parts", 0);
            number(r, message, "first_fragment_us", event.radio.done_us);
            number(r, message, "complete_us", r->port.now_us(r->port.context));
            send(r, "message.result", message);
        }
    }
    if (event.result_ready && r->sender) send(r, "echo.result", echo_result(r));
    if (status->done)
    {
        finish(r, status->failed ? eq(status->reason, "timeout") ? "timeout" : "error" : "completed",
               status->failed);
        return;
    }
    rf_phase phase = status->valid || eq(status->reason, "timeout") || eq(status->reason, "reply_sent")
                        ? RF_DRAINING : status->request_seen ? RF_RUNNING : r->phase;
    if (phase != r->phase) { r->phase = phase; state(r); }
}
static void fault_observation(rf_execution *r)
{
    if (!r->faults || !r->port.room(r->port.context, 1)) return;
    if (!r->fault_pending_valid) r->fault_pending_valid = rf_faults_pop(r->faults, &r->fault_pending);
    if (!r->fault_pending_valid) return;
    cJSON *o = rf_fault_json_entry(&r->fault_pending);
    if (o) string(r, o, "session_id", r->plan.session_text);
    if (o && send(r, "fault.applied", o)) r->fault_pending_valid = false;
}
static bool poll_extra_transmission(rf_execution *r)
{
    node_radio_event event;
    if (!node_radio_poll(r->radio, &event)) return false;
    cJSON *o = object(r);
    string(r, o, "injection_id", r->replay_id); string(r, o, "session_id", r->plan.session_text);
    number(r, o, "frame_seq", event.reference.frame_seq); number(r, o, "message_id", event.reference.message_id);
    number(r, o, "fragment_index", event.reference.fragment_index); number(r, o, "frame_bytes", event.frame_bytes);
    if (event.command_us >= 0) number(r, o, "tx_command_us", event.command_us); else string(r, o, "tx_command_us", NULL);
    if (event.done_us >= 0) number(r, o, "tx_done_us", event.done_us); else string(r, o, "tx_done_us", NULL);
    string(r, o, "status", event.status == RADIO_DONE ? "completed" : "failed");
    wire_digest(r, o, r->replay_view.after);
    send(r, "fault.tx", o); r->injected_tx = false;
    if (event.status != RADIO_DONE) { finish(r, "error", true); return false; }
    return true;
}

static void fault_drain(rf_execution *r)
{
    if (r->injected_tx && !poll_extra_transmission(r)) return;
    if (r->port.now_us(r->port.context) >= r->drain_deadline) finish(r, "completed", false);
}

static void next_fragment(rf_execution *r)
{
    r->tx_fragment++;
    int64_t now = r->port.now_us(r->port.context);
    if (r->tx_fragment < r->fragments.fragment_count)
        r->next_tx = now + r->plan.link.guard_us;
    else if (r->plan.fixed_source) {
        encoded_queue_complete(r->queue, r->active_message, SOURCE_SENT);
        r->active_message = 0;
        r->source_finished_messages++;
    } else if (r->plan.fault_us) {
        r->phase = RF_DRAINING;
        r->drain_deadline = now + r->plan.fault_us + r->plan.drain;
        if (r->drain_deadline > r->deadline) r->drain_deadline = r->deadline;
        state(r);
    } else finish(r, "completed", false);
}

static void duplicate_work(rf_execution *r)
{
    if (r->injected_tx) {
        if (poll_extra_transmission(r)) {
            r->duplicate_due = -1;
            next_fragment(r);
        }
        return;
    }
    int64_t now = r->port.now_us(r->port.context);
    if (now < r->duplicate_due) return;
    rf_fault_view view;
    const uint8_t *wire = rf_faults_duplicate(r->faults, r->wire_fragment, &view);
    if (!wire) { finish(r, "error", true); return; }
    node_radio_reference ref = {r->plan.session, view.sequence, view.spec.message,
        view.spec.fragment, view.spec.attempt};
    uint32_t timeout = rf_radio_airtime_us(&r->radio->applied, view.frame_bytes) + 80000;
    if (r->deadline - now < timeout) {
        finish(r, "timeout", true);
        return;
    }
    if (!node_radio_tx(r->radio, wire, view.frame_bytes, &ref, timeout) ||
        !rf_faults_duplicated(r->faults, view.spec.id, now)) {
        finish(r, "error", true);
        return;
    }
    r->injected_tx = true;
    r->replay_view = view;
    memcpy(r->replay_id, view.spec.id, sizeof(r->replay_id));
}
void rf_execution_tick(rf_execution *r)
{
    r->oom = false;
    fault_observation(r);
    if (r->phase == RF_IDLE)
        return;
    r->oom = false;
    if (r->phase == RF_REPORTING)
    {
        if (r->port.now_us(r->port.context) >= r->deadline)
            rf_execution_abort(r, "timeout", false);
        else
            report_failure(r);
        return;
    }
    if ((r->phase == RF_PREPARING || r->phase == RF_PREPARED) &&
        r->port.now_us(r->port.context) >= r->deadline) {
        rf_execution_abort(r, "timeout", false);
        return;
    }
    if (r->phase == RF_PREPARING)
    {
        if (!r->port.room(r->port.context, 3))
            return;
        cJSON *prepared = object(r);
        number(r, prepared, "config_revision", r->plan.revision);
        add(r, prepared, "budget", budget(r, &r->plan));
        number(r, prepared, "source_length_bytes", r->plan.bytes);
        string(r, prepared, "source_sha256", r->sha_hex);
        send(r, "run.prepared", prepared);
        cJSON *result = object(r);
        string(r, result, "artifact_id", r->artifact_id);
        string(r, result, "artifact_state", r->sender ? "committed" : "reserved");
        string(r, result, "sha256", r->sha_hex);
        number(r, result, "length_bytes", r->plan.bytes);
        operation(r, true, result);
        r->phase = RF_PREPARED;
        state(r);
        return;
    }
    if (r->phase == RF_PREPARED)
        return;
    if (r->phase == RF_ARMED && r->sender) {
        if (r->port.now_us(r->port.context) >= r->arm_deadline)
            rf_execution_abort(r, "timeout", false);
        return;
    }
    if (r->plan.echo)
    {
        if (r->port.now_us(r->port.context) >= r->deadline)
            rf_execution_abort(r, "timeout", false);
        else {
            node_radio_poll(r->radio, NULL);
            if (r->port.room(r->port.context, 6)) echo_work(r);
        }
        return;
    }
    if (r->port.now_us(r->port.context) >= r->deadline) {
        if (r->plan.fixed_source) finish(r, "completed", false);
        else rf_execution_abort(r, "timeout", false);
        return; // Resource cleanup must not depend on telemetry space.
    }
    if (r->plan.fixed_source && r->sender && r->phase == RF_RUNNING) {
        encoded_source_status source;
        encoded_queue_snapshot(r->queue, &source);
        if (source.phase == SOURCE_DRAINING) { r->phase = RF_DRAINING; state(r); }
    }
    node_radio_poll(r->radio, NULL);
    if (!r->port.room(r->port.context, 6))
        return;
    if (r->sender && r->phase == RF_DRAINING && r->plan.fault_us) { fault_drain(r); return; }
    if (r->sender && r->duplicate_due >= 0) { duplicate_work(r); return; }
    if (!r->sender && receiver_ack_work(r))
        return;
    node_radio_event event;
    if (r->sender)
    {
        if (r->plan.fixed_source && !r->active_message) {
            encoded_source_status source;
            encoded_queue_snapshot(r->queue, &source);
            if (source.phase >= SOURCE_FINISHED) { finish(r, "completed", false); return; }
            encoded_source_message message;
            if (!encoded_queue_take(r->queue, &message)) return;
            r->active_message = message.message_id;
            r->payload = message.data;
            r->tx_fragment = 0;
            uint32_t sequence;
            if (rf_secure_reserve(r->security, r->fragments.fragment_count, &sequence) != RF_CRYPTO_OK ||
                !rf_message_plan_init(&r->fragments, r->plan.session, sequence, message.message_id,
                    r->plan.source, r->plan.role == 1 ? 2 : 1, 1, true,
                    r->plan.link.ack_requested, SOURCE_MESSAGE_BYTES, r->plan.link.fragment_payload_bytes)) {
                finish(r, "error", true); return;
            }
            r->next_tx = r->port.now_us(r->port.context);
        }
        int64_t now = r->port.now_us(r->port.context);
        if (r->next_tx >= 0)
        {
            if (now >= r->deadline)
                finish(r, "timeout", true);
            else if (now >= r->next_tx) {
                uint32_t body = r->tx_fragment + 1 < r->fragments.fragment_count ?
                    r->fragments.fragment_bytes : r->plan.bytes - r->tx_fragment * r->fragments.fragment_bytes;
                uint64_t worst = (uint64_t)(1 + r->plan.link.max_retries) *
                    (rf_radio_airtime_us(&r->radio->applied, 40 + body + (r->plan.protected_mode ? 16 : 0)) +
                     80000 + r->plan.ack_timeout + r->plan.link.guard_us);
                if (r->plan.fixed_source && (uint64_t)(r->deadline - now) < worst) {
                    encoded_queue_complete(r->queue, r->active_message, SOURCE_DISCARDED);
                    r->active_message = 0;
                    r->source_finished_messages++;
                    r->next_tx = -1;
                } else if (!transmit(r)) finish(r, "error", true);
            }
            return;
        }
        bool observed = rf_sender_poll(r->transmitter, &event);
        rf_sender_status status;
        rf_sender_snapshot(r->transmitter, &status);
        sender_counts(r, &status);
        if (!observed)
        {
            if ((status.state == RF_SENDER_FAILED || status.state == RF_SENDER_CANCELLED) &&
                !continue_source_after_failure(r, &status))
                finish(r, status.state == RF_SENDER_FAILED ? "timeout" : "error", true);
            return;
        }
    }
    else if (!node_radio_poll(r->radio, &event))
        return;
    if (r->sender)
    {
        if (event.kind == RADIO_EVENT_TX)
        {
            tx_observation(r, &event, "data");
            if (event.status == RADIO_DONE && !r->frame_originals)
            {
                r->originals++;
                r->frame_originals = 1;
            }
            if (r->first_tx < 0)
                r->first_tx = event.command_us;
            r->last_tx = event.done_us;
        }
        else
            received_ack(r, &event);
        rf_sender_status status;
        rf_sender_snapshot(r->transmitter, &status);
        if (r->plan.protected_mode && event.kind == RADIO_EVENT_RX && event.signal_valid &&
            event.crc_ok && status.last_ack_acceptance != RF_SECURE_ACCEPTED)
            rejected_at(r, status.last_ack_acceptance == RF_SECURE_AUTH_FAILED
                               ? "authentication_failed"
                           : status.last_ack_acceptance == RF_SECURE_REPLAY  ? "replay"
                           : status.last_ack_acceptance == RF_SECURE_TOO_OLD ? "too_old"
                           : rf_sender_wrong_ack_reference(r->transmitter)  ? "wrong_reference"
                                                                             : "invalid_frame",
                        NULL, event.done_us);
        bool ack_received = status.state == RF_SENDER_COMPLETED && status.acks;
        bool ack_timeout = event.status == RADIO_TIMEOUT;
        if (event.kind == RADIO_EVENT_RX && (ack_received || ack_timeout))
        {
            cJSON *ack = object(r);
            number(r, ack, "acked_frame_seq", r->fragments.first_sequence + r->wire_fragment);
            if (ack_received)
                number(r, ack, "ack_frame_seq", word(event.bytes + 16));
            else
                string(r, ack, "ack_frame_seq", NULL);
            number(r, ack, "attempt_index", status.attempts);
            string(r, ack, "status", ack_received ? "received" : "timeout");
            send(r, "ack.result", ack);
        }
        if (status.state == RF_SENDER_COMPLETED)
        {
            rf_fault_view duplicate;
            if (rf_faults_duplicate(r->faults, r->wire_fragment, &duplicate))
                r->duplicate_due = r->port.now_us(r->port.context) + duplicate_guard(&r->plan.link);
            else next_fragment(r);
        }
        else if ((status.state == RF_SENDER_FAILED || status.state == RF_SENDER_CANCELLED) &&
            !continue_source_after_failure(r, &status))
            finish(r, event.status == RADIO_TIMEOUT ? "timeout" : "error", true);
        return;
    }
    rf_data_view h;
    bool decoded =
        event.status == RADIO_DONE &&
        rf_data_inspect(event.bytes, event.frame_bytes, r->plan.link.fragment_payload_bytes, &h);
    if (event.signal_valid)
    {
        r->observations++;
        if (r->first_rx < 0)
            r->first_rx = event.done_us;
        r->last_rx = event.done_us;
        cJSON *o = object(r);
        char session[17];
        if (decoded)
            snprintf(session, 17, "%016" PRIx64, h.session);
        string(r, o, "session_id", decoded ? session : NULL);
        string(r, o, "source_role", decoded ? (h.source == 1 ? "A" : "B") : NULL);
        if (decoded)
        {
            number(r, o, "frame_seq", h.frame_sequence);
            number(r, o, "message_id", h.message_id);
            number(r, o, "fragment_index", h.fragment_index);
        }
        else
        {
            string(r, o, "frame_seq", NULL);
            string(r, o, "message_id", NULL);
            string(r, o, "fragment_index", NULL);
        }
        string(r, o, "frame_type", decoded ? "data" : NULL);
        number(r, o, "frame_bytes", event.frame_bytes);
        number(r, o, "rx_done_us", event.done_us);
        add(r, o, "rssi_dbm", cJSON_CreateNumber(event.rssi_dbm));
        add(r, o, "snr_db", cJSON_CreateNumber(event.snr_db));
        add(r, o, "crc_ok", cJSON_CreateBool(event.crc_ok));
        if (decoded && r->faults && event.crc_ok) {
            uint8_t digest[32];
            if (r->port.hash(r->port.context, event.bytes, event.frame_bytes, digest))
                wire_digest(r, o, digest);
        }
        send(r, "rx.frame", o);
    }
    if (event.status == RADIO_TIMEOUT && resume_receive(r))
        return;
    if (event.status == RADIO_TIMEOUT || event.status == RADIO_CANCELLED ||
        event.status == RADIO_FAILED)
    {
        finish(r, event.status == RADIO_TIMEOUT ? "timeout" : "error", true);
        return;
    }
    uint8_t digest[32];
    rf_acceptance accepted = RF_INVALID_FRAME;
    rf_reassembly_result insertion = RF_REASSEMBLY_REJECTED;
    const char *security_rejection = NULL;
    rf_fault_match dropped = RF_FAULT_NO_MATCH;
    if (decoded && event.crc_ok && h.session != r->plan.session)
        accepted = RF_WRONG_SESSION;
    else if (decoded && event.crc_ok &&
             (h.source != r->plan.source || h.destination != r->plan.role))
        accepted = RF_WRONG_ROLE;
    else if (decoded && event.crc_ok && !!(h.flags & 1) != r->plan.protected_mode)
        security_rejection = "protection_mismatch";
    else if (decoded && event.crc_ok && r->plan.protected_mode)
    {
        protected_insertion call = {.execution = r, .header = &h, .event = &event,
            .insertion = RF_REASSEMBLY_REJECTED, .accepted = RF_INVALID_FRAME};
        rf_secure_acceptance decision =
            rf_secure_receive(r->security, event.bytes, event.frame_bytes, event.done_us,
                              r->plan.link.ack_requested, r->plan.drain, insert_protected, &call);
        insertion = call.insertion;
        accepted = call.accepted;
        dropped = call.fault;
        if (insertion == RF_REASSEMBLY_HASH_FAILED)
            security_rejection = "content_mismatch";
        if (decision == RF_SECURE_RETRY_DUPLICATE)
        {
            insertion = RF_REASSEMBLY_DUPLICATE;
            accepted = RF_DUPLICATE;
        }
        else if (decision == RF_SECURE_AUTH_FAILED)
            security_rejection = "authentication_failed";
        else if (decision == RF_SECURE_REPLAY)
            security_rejection = "replay";
        else if (decision == RF_SECURE_TOO_OLD)
            security_rejection = "too_old";
        else if (decision == RF_SECURE_UNAVAILABLE)
        {
            accepted = RF_INTERNAL_ERROR;
            security_rejection = "crypto_unavailable";
        }
    }
    else if (decoded && event.crc_ok)
    {
        if (h.session != r->plan.session)
            accepted = RF_WRONG_SESSION;
        else if (h.source != r->plan.source || h.destination != r->plan.role)
            accepted = RF_WRONG_ROLE;
        else if (h.message_id != 1 || h.message_bytes != r->plan.bytes ||
                 h.fragment_count != r->fragments.fragment_count || h.content ||
                 h.flags != (r->plan.link.ack_requested ? 2 : 0))
            accepted = RF_WRONG_MESSAGE;
        else if (memcmp(h.body,
                        r->payload + (uint32_t)h.fragment_index * r->fragments.fragment_bytes,
                        h.body_bytes))
            accepted = RF_CONTENT_MISMATCH;
        else
        {
            dropped = receiver_fault(r, RF_FAULT_DROP, &h, &event);
            if (dropped == RF_FAULT_NO_MATCH) {
                insertion =
                    rf_reassembly_accept(r->receiver, event.bytes, event.frame_bytes, event.done_us);
            }
            accepted = insertion == RF_REASSEMBLY_DUPLICATE ? RF_DUPLICATE
                       : insertion == RF_REASSEMBLY_ACCEPTED || insertion == RF_REASSEMBLY_COMPLETE
                           ? RF_DELIVERED
                           : RF_INTERNAL_ERROR;
        }
    }
    if (dropped != RF_FAULT_NO_MATCH) {
        if (dropped == RF_FAULT_OBSERVATION_FAILED || !resume_receive(r))
            finish(r, "error", true);
        return;
    }
    if (accepted == RF_DELIVERED)
    {
        if (r->plan.fixed_source && r->phase == RF_ARMED) { r->phase = RF_RUNNING; state(r); }
        r->accepted++;
        if (r->first_fragment < 0)
            r->first_fragment = event.done_us;
        cJSON *o = object(r);
        string(r, o, "session_id", r->plan.session_text);
        string(r, o, "source_role", r->plan.source == 1 ? "A" : "B");
        number(r, o, "frame_seq", h.frame_sequence);
        number(r, o, "message_id", r->plan.fixed_source ? (r->sender ? r->active_message : r->received_message) : 1);
        number(r, o, "fragment_index", h.fragment_index);
        number(r, o, "payload_bytes", h.body_bytes);
        number(r, o, "accepted_us", r->port.now_us(r->port.context));
        send(r, "rx.accepted", o);
    }
    else if (accepted == RF_DUPLICATE)
        r->duplicates++;
    const void *complete = NULL;
    size_t complete_bytes = 0;
    if (insertion == RF_REASSEMBLY_COMPLETE &&
        rf_reassembly_take(r->receiver, &complete, &complete_bytes, digest) &&
        complete_bytes == r->plan.bytes && (r->plan.fixed_source ?
            (memcpy(r->recovered_output + (h.message_id - 1) * SOURCE_MESSAGE_BYTES, complete, complete_bytes), true) : publish_bytes(r, complete)))

    {
        if (r->plan.fixed_source) r->delivered_bitmap |= 1U << (h.message_id - 1);
        r->delivered++;
        hex(digest, r->sha_hex);
        cJSON *o = object(r);
        number(r, o, "message_id", r->plan.fixed_source ? (r->sender ? r->active_message : r->received_message) : 1);
        string(r, o, "status", "delivered");
        number(r, o, "message_bytes", r->plan.bytes);
        string(r, o, "sha256", r->sha_hex);
        number(r, o, "fragment_count", r->fragments.fragment_count);
        number(r, o, "missing_count", 0);
        number(r, o, "missing_parts", 0);
        number(r, o, "first_fragment_us", r->first_fragment);
        number(r, o, "complete_us", r->port.now_us(r->port.context));
        send(r, "message.result", o);
        if (!r->plan.fixed_source && !r->plan.link.ack_requested && !r->plan.fault_us)
        {
            finish(r, "completed", false);
            return;
        }
        if (!r->plan.fixed_source) r->phase = RF_DRAINING;
        int64_t now = r->port.now_us(r->port.context);
        r->drain_deadline = r->deadline - now < r->plan.drain ? r->deadline : now + r->plan.drain + r->plan.fault_us;
        if (r->drain_deadline > r->deadline) r->drain_deadline = r->deadline;
    }
    if (r->plan.link.ack_requested &&
        (insertion == RF_REASSEMBLY_ACCEPTED || insertion == RF_REASSEMBLY_COMPLETE ||
         insertion == RF_REASSEMBLY_DUPLICATE))
    {
        rf_ack_classification classification =
            insertion == RF_REASSEMBLY_DUPLICATE ? RF_ACK_RETRY_DUPLICATE : RF_ACK_NEW_DATA;
        if (r->plan.protected_mode)
        {
            memcpy(r->protected_ack_header, event.bytes, 40);
            r->protected_ack_due = event.done_us + 20000;
        }
        else if (!rf_ack_offer(r->acknowledgments, event.bytes, event.frame_bytes, classification,
                               event.done_us))
        {
            finish(r, "error", true);
            return;
        }
        rf_fault_match suppressed = receiver_fault(r, RF_FAULT_DROP_ACK, &h, &event);
        if (suppressed != RF_FAULT_NO_MATCH) {
            rf_ack_suppress(r->acknowledgments); // Preserve accepted-frame retry eligibility.
            if (suppressed == RF_FAULT_OBSERVATION_FAILED || !resume_receive(r))
                finish(r, "error", true);
            return;
        }
        r->ack_pending = true;
        return;
    }
    if (accepted != RF_DELIVERED)
        rejected_at(r, security_rejection             ? security_rejection
                    : accepted == RF_CONTENT_MISMATCH ? "content_mismatch"
                    : accepted == RF_WRONG_SESSION    ? "wrong_session"
                    : accepted == RF_WRONG_ROLE       ? "wrong_source"
                    : accepted == RF_DUPLICATE        ? "duplicate"
                    : event.crc_ok                    ? "invalid_frame"
                                                      : "phy_crc_or_header",
                    decoded && event.crc_ok ? &h : NULL, event.done_us);
    int64_t until = !r->plan.fixed_source && r->delivered ? r->drain_deadline : r->receive_deadline;
    int64_t remaining = until - r->port.now_us(r->port.context);
    if (remaining <= 0 || accepted == RF_INTERNAL_ERROR || (!r->plan.fixed_source && !r->plan.fault_us && insertion == RF_REASSEMBLY_COMPLETE) ||
        !node_radio_rx(r->radio, 255, remaining > 30000000 ? 30000000 : remaining))
        finish(r, "error", true);
}

void rf_execution_memory(const rf_execution *r, node_memory_inventory *out)
{
    node_memory_add(out, "rf_generated", r->generated, r->plan.bytes);
    encoded_queue_memory(r->queue, out);
    rf_echo_memory(r->echo, out);
    rf_faults_memory(r->faults, out);
    rf_sender_memory(r->transmitter, out);
    rf_reassembly_memory(r->receiver, out);
    rf_ack_memory(r->acknowledgments, out);
    rf_secure_memory(r->security, out);
}
