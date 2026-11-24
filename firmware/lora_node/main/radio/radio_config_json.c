#include "radio/radio_config_json.h"
#include "protocol/strict_json.h"
#include <string.h>

static bool keys(const cJSON *o, const char *const *allowed, size_t count)
{
    if (!cJSON_IsObject(o)) return false;
    for (const cJSON *v = o->child; v; v = v->next) {
        size_t i = 0;
        while (i < count && strcmp(v->string, allowed[i])) i++;
        if (i == count) return false;
    }
    return true;
}
static bool integer(const cJSON *o, const char *key, uint32_t low, uint32_t high, uint32_t fallback, uint32_t *out)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, key);
    if (!v) { *out = fallback; return true; }
    if (!strict_json_integer(v) || v->valuedouble < low || v->valuedouble > high) return false;
    *out = (uint32_t)v->valuedouble;
    return true;
}
static bool literal(const cJSON *o, const char *key, const char *expected)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, key);
    return !v || (cJSON_IsString(v) && !strcmp(v->valuestring, expected));
}
bool radio_config_parse(const cJSON *args, node_radio_settings *radio, node_link_settings *link)
{
    const char *const outer[] = {"radio", "link"};
    const char *const radios[] = {"frequency_hz", "bandwidth_hz", "spreading_factor", "coding_rate_denominator",
        "tx_power_dbm", "preamble_symbols", "header_mode", "crc_enabled", "iq_inverted", "sync_word", "ldro_mode"};
    const char *const links[] = {"fragment_payload_bytes", "ack_mode", "max_retries", "guard_us", "ack_turnaround_us", "ack_margin_us"};
    const cJSON *r = cJSON_GetObjectItemCaseSensitive(args, "radio"), *l = cJSON_GetObjectItemCaseSensitive(args, "link");
    if (!keys(args, outer, 2) || !keys(r, radios, 11) || !keys(l, links, 6)) return false;
    uint32_t freq, bw, sf, cr, power, preamble, sync, retries, turn, margin, fragment, guard;
    if (!integer(r,"frequency_hz",902000000,928000000,915000000,&freq) ||
        !integer(r,"bandwidth_hz",125000,500000,125000,&bw) ||
        !integer(r,"spreading_factor",7,12,7,&sf) || !integer(r,"coding_rate_denominator",5,8,5,&cr) ||
        !integer(r,"tx_power_dbm",2,20,14,&power) || !integer(r,"preamble_symbols",8,32,8,&preamble) ||
        !integer(r,"sync_word",5156,5156,5156,&sync) || !literal(r,"header_mode","explicit") || !literal(r,"ldro_mode","auto") ||
        !literal(l,"ack_mode","none") || !integer(l,"max_retries",0,0,0,&retries) ||
        !integer(l,"fragment_payload_bytes",16,215,160,&fragment) || !integer(l,"guard_us",0,1000000,50000,&guard) ||
        !integer(l,"ack_turnaround_us",20000,20000,20000,&turn) || !integer(l,"ack_margin_us",80000,80000,80000,&margin)) return false;
    const cJSON *crc = cJSON_GetObjectItemCaseSensitive(r,"crc_enabled"), *iq = cJSON_GetObjectItemCaseSensitive(r,"iq_inverted");
    if ((crc && !cJSON_IsTrue(crc)) || (iq && !cJSON_IsFalse(iq))) return false;
    *radio = (node_radio_settings){freq,bw,sf,cr,power,preamble};
    *link = (node_link_settings){fragment,guard};
    return node_radio_valid_settings(radio);
}
#define ADD(call) do { if (!(call)) { cJSON_Delete(o); return NULL; } } while (0)
cJSON *radio_config_radio(const node_radio_settings *s, bool ldro)
{
    cJSON *o = cJSON_CreateObject(); if (!o) return NULL;
    ADD(cJSON_AddNumberToObject(o,"frequency_hz",s->frequency_hz));
    ADD(cJSON_AddNumberToObject(o,"bandwidth_hz",s->bandwidth_hz));
    ADD(cJSON_AddNumberToObject(o,"spreading_factor",s->spreading_factor));
    ADD(cJSON_AddNumberToObject(o,"coding_rate_denominator",s->coding_rate_denominator));
    ADD(cJSON_AddNumberToObject(o,"tx_power_dbm",s->tx_power_dbm));
    ADD(cJSON_AddNumberToObject(o,"preamble_symbols",s->preamble_symbols));
    ADD(cJSON_AddStringToObject(o,"header_mode","explicit"));
    ADD(cJSON_AddTrueToObject(o,"crc_enabled")); ADD(cJSON_AddFalseToObject(o,"iq_inverted"));
    ADD(cJSON_AddNumberToObject(o,"sync_word",5156)); ADD(cJSON_AddStringToObject(o,"ldro_mode","auto"));
    ADD(cJSON_AddBoolToObject(o,"ldro_enabled",ldro));
    return o;
}
cJSON *radio_config_link(const node_link_settings *s)
{
    cJSON *o = cJSON_CreateObject(); if (!o) return NULL;
    ADD(cJSON_AddNumberToObject(o,"fragment_payload_bytes",s->fragment_payload_bytes));
    ADD(cJSON_AddStringToObject(o,"ack_mode","none")); ADD(cJSON_AddNumberToObject(o,"max_retries",0));
    ADD(cJSON_AddNumberToObject(o,"guard_us",s->guard_us));
    ADD(cJSON_AddNumberToObject(o,"ack_turnaround_us",20000)); ADD(cJSON_AddNumberToObject(o,"ack_margin_us",80000));
    return o;
}
cJSON *radio_config_result(const node_radio_settings *s, const node_link_settings *l, uint32_t revision)
{
    cJSON *o = cJSON_CreateObject(); if (!o) return NULL;
    cJSON *r = radio_config_radio(s,(1U << s->spreading_factor)*1000U >= 16U*s->bandwidth_hz);
    if (!r || !cJSON_AddItemToObject(o,"radio",r)) { cJSON_Delete(r); cJSON_Delete(o); return NULL; }
    cJSON *link = radio_config_link(l);
    if (!link || !cJSON_AddItemToObject(o,"link",link)) { cJSON_Delete(link); cJSON_Delete(o); return NULL; }
    ADD(cJSON_AddNumberToObject(o,"config_revision",revision));
    return o;
}
