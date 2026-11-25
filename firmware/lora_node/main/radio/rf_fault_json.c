#include "radio/rf_fault_json.h"
#include <string.h>

static const char *text(const cJSON *o, const char *key)
{
    return cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, key));
}
static bool equal(const char *a, const char *b) { return a && b && !strcmp(a, b); }
static bool exact_keys(const cJSON *o, const char *const *keys, size_t count)
{
    if (!cJSON_IsObject(o) || cJSON_GetArraySize(o) != (int)count) return false;
    for (size_t i = 0; i < count; i++)
        if (!cJSON_GetObjectItemCaseSensitive(o, keys[i])) return false;
    return true;
}
static bool integer(const cJSON *o, const char *key, uint32_t low, uint32_t high, uint32_t *out)
{
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(o, key);
    if (!cJSON_IsNumber(value) || value->valuedouble < low || value->valuedouble > high ||
        value->valuedouble != (uint32_t)value->valuedouble) return false;
    *out = (uint32_t)value->valuedouble;
    return true;
}
static bool null(const cJSON *o, const char *key)
{
    return cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(o, key));
}
bool rf_fault_json_parse(const cJSON *args, rf_fault_spec out[RF_FAULT_BATCH], size_t *count,
                         bool *replace)
{
    const char *const outer[] = {"injections", "replace"};
    const char *const keys[] = {"injection_id", "stage", "action", "message_id", "fragment_index",
        "attempt_index", "byte_offset", "xor_mask", "block_size"};
    const cJSON *entries = cJSON_GetObjectItemCaseSensitive(args, "injections"),
                *flag = cJSON_GetObjectItemCaseSensitive(args, "replace");
    if (!exact_keys(args, outer, 2) || !cJSON_IsArray(entries) || !cJSON_IsBool(flag) ||
        cJSON_GetArraySize(entries) > (int)RF_FAULT_BATCH) return false;
    *count = cJSON_GetArraySize(entries);
    *replace = cJSON_IsTrue(flag);
    for (size_t i = 0; i < *count; i++) {
        const cJSON *entry = cJSON_GetArrayItem(entries, i);
        const char *id = text(entry, "injection_id"), *stage = text(entry, "stage"),
                   *action = text(entry, "action");
        uint32_t message, fragment, attempt, offset = 0, mask = 0;
        if (!exact_keys(entry, keys, 9) || !id || strlen(id) != 36 || !null(entry, "block_size") ||
            !integer(entry, "message_id", 1, UINT32_MAX, &message) ||
            !integer(entry, "fragment_index", 0, RF_MESSAGE_FRAGMENTS - 1, &fragment) ||
            !integer(entry, "attempt_index", 1, 3, &attempt)) return false;
        uint8_t kind;
        if (equal(stage, "tx_after_protect") && equal(action, "xor_byte")) {
            kind = RF_FAULT_XOR;
            if (!integer(entry, "byte_offset", 40, 254, &offset) ||
                !integer(entry, "xor_mask", 1, 255, &mask)) return false;
        } else if (equal(stage, "tx_retained") && equal(action, "replay") &&
                   null(entry, "byte_offset") && null(entry, "xor_mask")) kind = RF_FAULT_REPLAY;
        else return false;
        out[i] = (rf_fault_spec){.message = message, .fragment = fragment, .attempt = attempt,
            .offset = offset, .mask = mask, .action = kind};
        memcpy(out[i].id, id, 37);
    }
    return true;
}
static bool number(cJSON *o, const char *key, int64_t value, bool present)
{
    return present ? cJSON_AddNumberToObject(o, key, value) != NULL :
                     cJSON_AddNullToObject(o, key) != NULL;
}
static bool digest(cJSON *o, const char *key, const uint8_t value[32], bool present)
{
    if (!present) return cJSON_AddNullToObject(o, key) != NULL;
    char hex[65];
    const char *digits = "0123456789abcdef";
    for (unsigned i = 0; i < 32; i++) { hex[2 * i] = digits[value[i] >> 4]; hex[2 * i + 1] = digits[value[i] & 15]; }
    hex[64] = 0;
    return cJSON_AddStringToObject(o, key, hex) != NULL;
}
cJSON *rf_fault_json_entry(const rf_fault_view *v)
{
    if (!v || v->state > RF_FAULT_MISSED) return NULL;
    const rf_fault_spec *s = &v->spec;
    bool mutation = s->action == RF_FAULT_XOR, observed = v->sequence != 0;
    cJSON *o = cJSON_CreateObject();
    if (!o || !cJSON_AddStringToObject(o, "injection_id", s->id) ||
        !cJSON_AddStringToObject(o, "stage", mutation ? "tx_after_protect" : "tx_retained") ||
        !cJSON_AddStringToObject(o, "action", mutation ? "xor_byte" : "replay") ||
        !number(o, "message_id", s->message, true) || !number(o, "fragment_index", s->fragment, true) ||
        !number(o, "attempt_index", s->attempt, true) || !number(o, "byte_offset", s->offset, mutation) ||
        !number(o, "xor_mask", s->mask, mutation) || !cJSON_AddNullToObject(o, "block_size") ||
        !cJSON_AddStringToObject(o, "state", (const char *[]){"planned", "retained", "applied", "fired", "disabled", "missed"}[v->state]) ||
        !number(o, "target_frame_seq", v->sequence, observed) || !number(o, "frame_bytes", v->frame_bytes, observed) ||
        !digest(o, "before_sha256", v->before, observed) || !digest(o, "after_sha256", v->after, observed) ||
        !number(o, "applied_us", v->applied_us, v->applied_us >= 0)) {
        cJSON_Delete(o);
        return NULL;
    }
    return o;
}
