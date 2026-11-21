#include "radio/rf_execution.h"
#include "protocol/chunk_bytes.h"
#include "protocol/strict_json.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *names[] = {"session.open", "session.close", "run.prepare", "run.arm",
                              "run.start",    "run.stop",      "run.summary"};
static const char *text(const cJSON *o, const char *k)
{
    return cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
}
static bool eq(const char *a, const char *b)
{
    return a && b && !strcmp(a, b);
}
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
    number(r, o, "fault_budget_us", 0);
    string(r, o, "model_version", "sx126x_lora_v1");
    return o;
}
static cJSON *summary(rf_execution *r)
{
    cJSON *o = object(r);
    string(r, o, "role", r->sender ? "sender" : "receiver");
    string(r, o, "session_id", r->plan.session_text);
    number(r, o, "config_revision", r->plan.revision);
    number(r, o, "intended_messages", 1);
    number(r, o, "started_messages", r->started);
    number(r, o, "finished_messages", r->finished && r->started);
    number(r, o, "original_packets", r->sender && r->attempts ? 1 : 0);
    number(r, o, "tx_attempts", r->attempts);
    number(r, o, "radio_observations", r->observations);
    number(r, o, "accepted_fragments", r->accepted);
    number(r, o, "duplicates", r->duplicates);
    number(r, o, "delivered_messages", r->delivered);
    number(r, o, "failed_messages", r->failed && r->started);
    number(r, o, "useful_source_bytes", r->sender ? r->plan.bytes : 0);
    number(r, o, "useful_delivered_bytes", r->delivered ? r->plan.bytes : 0);
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
    number(r, o, "telemetry_drops", r->port.drops(r->port.context) - r->drops_start);
    add(r, o, "validity_reasons", cJSON_CreateArray());
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
    for (unsigned i = 0; i < 7; i++)
        if (eq(name, names[i]))
            return true;
    return false;
}
bool rf_execution_busy(const rf_execution *r)
{
    return r->phase != RF_IDLE;
}
const char *rf_execution_state(const rf_execution *r)
{
    return (const char *[]){"idle", "preparing", "prepared", "armed", "running"}[r->phase];
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
    while (action < 7 && !eq(name, names[action]))
        action++;
    if (action == 7)
        return "UNSUPPORTED_COMMAND";
    p->action = (rf_action)action;
    if (!run)
        return "INVALID_ARGUMENT";
    if (action != RF_OPEN && (!r->plan.session || !eq(run, r->plan.run)))
        return "INVALID_STATE";
    if (action != RF_CLOSE && action != RF_STOP && action != RF_SUMMARY &&
        (!r->radio || !r->radio->available))
        return "MISSING_CAPABILITY";
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
            !eq(text(args, "security"), "none") || !null_value(args, "tx_key_hex") ||
            !null_value(args, "rx_key_hex"))
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
        if (r->used || r->phase != RF_IDLE || !r->radio->configured || !revision)
            return "INVALID_STATE";
        if (!allowed(args, outer, 2) || !allowed(s, specs, 14) || !allowed(b, budgets, 8) ||
            !literal(s, "catalog_id", "IF-02") || !literal(s, "source", "known_data") ||
            !literal(s, "security", "none") || !boolean(s, "playback", false) ||
            !null_value(s, "source_artifact_id") || !null_value(s, "sample_count") ||
            !null_value(s, "source_duration_ms") || !null_value(s, "expected_sha256") ||
            !integer(s, "message_count", 1, 10000, 100, &count) ||
            !integer(s, "message_bytes", 1, 65536, 64, &p->bytes) ||
            !integer(s, "source_seed", 0, UINT32_MAX, 743, &p->seed) ||
            !integer(s, "max_duration_ms", 1000, 3600000, 120000, &p->duration_ms))
            return "INVALID_ARGUMENT";
        if (count != 1 || p->bytes > link->fragment_payload_bytes || p->bytes > 215 ||
            p->duration_ms > 30000)
            return "RESOURCE_LIMIT";
        const char *direction = text(s, "direction");
        if (!direction)
            direction = "A_TO_B";
        if (!eq(direction, "A_TO_B") && !eq(direction, "B_TO_A"))
            return "INVALID_ARGUMENT";
        p->source = eq(direction, "A_TO_B") ? 1 : 2;
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
        if (!integer(b, "ack_timeout_us", 0, 0, 0, &p->ack_timeout) ||
            !integer(b, "reassembly_timeout_us", 1, 30000000, 0, &p->reassembly) ||
            !integer(b, "drain_us", 0, 30000000, 0, &p->drain) ||
            !integer(b, "processing_budget_us", 0, 30000000, 0, &p->processing) ||
            !integer(b, "capture_budget_us", 0, 0, 0, &unused) ||
            !integer(b, "playback_budget_us", 0, 0, 0, &unused) ||
            !integer(b, "fault_budget_us", 0, 0, 0, &unused) ||
            !literal(b, "model_version", "sx126x_lora_v1"))
            return "INVALID_ARGUMENT";
        unsigned free_slots = 0;
        for (unsigned i = 0; i < ARTIFACT_SLOTS; i++)
            if (!artifact_store_at(r->artifacts, i))
                free_slots++;
        if (!free_slots)
            return "RESOURCE_LIMIT";
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
        if (r->phase != RF_PREPARED || requested != revision || requested != r->plan.revision ||
            (action == RF_ARM && r->sender) || (action == RF_START && !r->sender))
            return "INVALID_STATE";
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
    else if (cJSON_GetArraySize(args))
        return "INVALID_ARGUMENT";
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
        else if (action == RF_ARM)
            add(r, *result, "receiver_ready", cJSON_CreateTrue());
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
static bool publish(rf_execution *r)
{
    if (artifact_store_put(r->artifacts, r->artifact_id, 0, r->payload, r->plan.bytes,
                           chunk_crc32(r->payload, r->plan.bytes)) != ARTIFACT_OK ||
        artifact_store_prepare_commit(r->artifacts, r->artifact_id, r->port.hash,
                                      r->port.context) != ARTIFACT_OK)
        return false;
    artifact_store_accept_commit(r->artifacts, r->artifact_id);
    return true;
}
bool rf_execution_apply(rf_execution *r, const rf_plan *p)
{
    if (p->action == RF_SUMMARY)
        return true;
    if (p->action == RF_OPEN)
    {
        r->plan = *p;
        r->used = false;
        r->finished = false;
        return true;
    }
    if (p->action == RF_STOP)
        return rf_execution_abort(r, p->reason, false);
    if (p->action == RF_CLOSE)
        return rf_execution_abort(r, "operator", true);
    if (p->action == RF_PREPARE)
    {
        r->plan = *p;
        r->sender = p->role == p->source;
        r->observations = r->accepted = r->duplicates = r->attempts = r->delivered = 0;
        r->first_tx = r->last_tx = r->first_rx = r->last_rx = -1;
        r->finished = r->failed = r->started = false;
        r->stop_reason = NULL;
        r->drops_start = r->port.drops(r->port.context);
        uint8_t digest[32];
        if (!rf_known_data(r->port.hash, r->port.context, p->seed, 1, r->payload, p->bytes) ||
            !r->port.hash(r->port.context, r->payload, p->bytes, digest))
            return false;
        hex(digest, r->sha_hex);
        uuid(r, r->artifact_id);
        artifact_spec spec = {r->artifact_id, r->sender ? "source" : "recovered", r->sha_hex,
                              "known_data", p->bytes};
        if (artifact_store_begin(r->artifacts, p->owner, &spec) != ARTIFACT_OK)
            return false;
        if (r->sender && !publish(r))
        {
            artifact_store_delete(r->artifacts, r->artifact_id);
            return false;
        }
        r->used = true;
        r->phase = RF_PREPARING;
        r->receiver =
            (rf_single_receiver){p->session, p->seed, 1, p->bytes, 0, 0, p->source, p->role};
        return true;
    }
    if (p->action == RF_ARM)
    {
        if (!node_radio_rx(r->radio, 255, p->duration_ms * 1000) || r->radio->operation != 2)
            return false;
        r->deadline = r->port.now_us(r->port.context) + (int64_t)p->duration_ms * 1000;
        r->phase = RF_ARMED;
        r->started = true;
        return true;
    }
    if (p->action == RF_START)
    {
        uint8_t frame[255];
        size_t length = rf_single_encode(p->session, 1, 1, p->source, p->source == 1 ? 2 : 1,
                                         r->payload, p->bytes, frame);
        node_radio_reference reference = {p->session, 1, 1, 0, 1};
        if (!length || !node_radio_tx(r->radio, frame, length, &reference, p->duration_ms * 1000))
            return false;
        r->plan = *p;
        r->attempts = 1;
        r->started = true;
        r->phase = RF_RUNNING;
        r->deadline = r->port.now_us(r->port.context) + (int64_t)p->duration_ms * 1000;
        return true;
    }
    return false;
}
static void finish(rf_execution *r, const char *reason, bool failed)
{
    bool operation_active = r->phase == RF_PREPARING || (r->sender && r->phase == RF_RUNNING);
    r->phase = RF_IDLE;
    r->stop_reason = reason;
    r->finished = true;
    r->failed = failed;
    if (failed && !r->sender)
        artifact_store_delete(r->artifacts, r->artifact_id);
    send(r, "run.summary", summary(r));
    if (operation_active)
    {
        cJSON *o = object(r);
        string(r, o, "kind", "known_data_tx");
        operation(r, !failed, failed ? (cJSON_Delete(o), (cJSON *)NULL) : o);
    }
    state(r);
}
bool rf_execution_abort(rf_execution *r, const char *reason, bool close)
{
    bool ok = true;
    if (r->radio && (r->radio->operation || r->radio->event_pending))
    {
        ok = node_radio_stop(r->radio);
        node_radio_event ignored;
        node_radio_poll(r->radio, &ignored);
    }
    if (rf_execution_busy(r))
        finish(r, reason, true);
    if (close)
    {
        artifact_store_release_owner(r->artifacts, r->plan.owner);
        r->plan.session = 0;
        r->used = false;
        r->phase = RF_IDLE;
    }
    return ok;
}
static void rejected(rf_execution *r, const char *reason)
{
    cJSON *o = object(r);
    string(r, o, "session_id", NULL);
    string(r, o, "source_role", NULL);
    string(r, o, "frame_seq", NULL);
    string(r, o, "message_id", NULL);
    string(r, o, "fragment_index", NULL);
    string(r, o, "stage",
           eq(reason, "wrong_session") || eq(reason, "wrong_source") ? "session"
           : eq(reason, "content_mismatch")                          ? "reassembly"
                                                                     : "framing");
    string(r, o, "reason", reason);
    string(r, o, "related_injection_id", NULL);
    send(r, "rx.rejected", o);
}
void rf_execution_tick(rf_execution *r)
{
    if (!rf_execution_busy(r))
        return;
    r->oom = false;
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
    node_radio_poll(r->radio, NULL);
    if (!r->port.room(r->port.context, 6))
        return;
    node_radio_event event;
    if (!node_radio_poll(r->radio, &event))
        return;
    if (r->sender)
    {
        cJSON *o = object(r);
        string(r, o, "session_id", r->plan.session_text);
        number(r, o, "frame_seq", 1);
        number(r, o, "message_id", 1);
        number(r, o, "fragment_index", 0);
        number(r, o, "attempt_index", 1);
        string(r, o, "frame_type", "data");
        number(r, o, "frame_bytes", event.frame_bytes);
        if (event.command_us >= 0)
            number(r, o, "tx_command_us", event.command_us);
        else
            string(r, o, "tx_command_us", NULL);
        if (event.done_us >= 0)
            number(r, o, "tx_done_us", event.done_us);
        else
            string(r, o, "tx_done_us", NULL);
        string(r, o, "status", event.status == RADIO_DONE ? "completed" : "failed");
        send(r, "tx.attempt", o);
        r->first_tx = event.command_us;
        r->last_tx = event.done_us;
        finish(r,
               event.status == RADIO_DONE      ? "completed"
               : event.status == RADIO_TIMEOUT ? "timeout"
                                               : "error",
               event.status != RADIO_DONE);
        return;
    }
    rf_single_header h;
    bool decoded =
        event.status == RADIO_DONE && rf_single_decode(event.bytes, event.frame_bytes,
                                                       r->plan.bytes < 16 ? 16 : r->plan.bytes, &h);
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
            number(r, o, "frame_seq", h.frame_seq);
            number(r, o, "message_id", h.message_id);
            number(r, o, "fragment_index", 0);
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
        send(r, "rx.frame", o);
    }
    if (event.status == RADIO_TIMEOUT || event.status == RADIO_CANCELLED ||
        event.status == RADIO_FAILED)
    {
        finish(r, event.status == RADIO_TIMEOUT ? "timeout" : "error", true);
        return;
    }
    uint8_t digest[32];
    rf_acceptance accepted =
        decoded ? rf_single_accept(&r->receiver, event.bytes, event.frame_bytes,
                                   r->plan.bytes < 16 ? 16 : r->plan.bytes, r->port.hash,
                                   r->port.context, r->payload, digest)
                : RF_INVALID_FRAME;
    if (accepted == RF_DELIVERED && publish(r))
    {
        r->accepted = r->delivered = 1;
        hex(digest, r->sha_hex);
        cJSON *o = object(r);
        string(r, o, "session_id", r->plan.session_text);
        string(r, o, "source_role", r->plan.source == 1 ? "A" : "B");
        number(r, o, "frame_seq", h.frame_seq);
        number(r, o, "message_id", h.message_id);
        number(r, o, "fragment_index", 0);
        number(r, o, "payload_bytes", r->plan.bytes);
        number(r, o, "accepted_us", r->port.now_us(r->port.context));
        send(r, "rx.accepted", o);
        o = object(r);
        number(r, o, "message_id", 1);
        string(r, o, "status", "delivered");
        number(r, o, "message_bytes", r->plan.bytes);
        string(r, o, "sha256", r->sha_hex);
        number(r, o, "fragment_count", 1);
        number(r, o, "missing_count", 0);
        number(r, o, "missing_parts", 0);
        number(r, o, "first_fragment_us", event.done_us);
        number(r, o, "complete_us", r->port.now_us(r->port.context));
        send(r, "message.result", o);
        finish(r, "completed", false);
        return;
    }
    rejected(r, accepted == RF_CONTENT_MISMATCH ? "content_mismatch"
                : accepted == RF_WRONG_SESSION  ? "wrong_session"
                : accepted == RF_WRONG_ROLE     ? "wrong_source"
                : event.crc_ok                  ? "invalid_frame"
                                                : "phy_crc_or_header");
    int64_t remaining = r->deadline - r->port.now_us(r->port.context);
    if (remaining <= 0 || accepted == RF_INTERNAL_ERROR || accepted == RF_DELIVERED ||
        !node_radio_rx(r->radio, 255, remaining))
        finish(r, "error", true);
}
