#include "radio/rf_ack.h"
#include "radio/rf_fragments.h"
#include <string.h>

#define ACK_CACHE 16U
typedef struct
{
    uint8_t header[40], digest[32];
    int64_t expires;
    bool used;
} ack_entry;
struct rf_ack_receiver
{
    rf_packet_port port;
    uint64_t session;
    uint32_t sequence, turnaround, horizon;
    uint16_t fragment;
    uint8_t local, peer, next, pending;
    bool queued, exhausted;
    int64_t due;
    ack_entry cache[ACK_CACHE];
};
static uint64_t be(const uint8_t *p, unsigned n)
{
    uint64_t value = 0;
    while (n--)
        value = (value << 8) | *p++;
    return value;
}
static void put(uint8_t *p, uint32_t value)
{
    for (unsigned i = 4; i; value >>= 8)
        p[--i] = value;
}
rf_ack_receiver *rf_ack_create(rf_packet_port port, uint64_t session, uint8_t local, uint8_t peer,
                               uint16_t fragment, uint32_t sequence, uint32_t turnaround,
                               uint32_t horizon)
{
    rf_message_plan plan;
    if (!port.allocate || !port.release || !port.hash || !sequence || !horizon ||
        horizon > 3600000000U || turnaround >= horizon ||
        !rf_message_plan_init(&plan, session, 1, 1, peer, local, 0, false, true, 1, fragment))
        return NULL;
    rf_ack_receiver *r = port.allocate(port.context, sizeof(*r));
    if (!r)
        return NULL;
    memset(r, 0, sizeof(*r));
    r->port = port;
    r->session = session;
    r->local = local;
    r->peer = peer;
    r->fragment = fragment;
    r->sequence = sequence;
    r->turnaround = turnaround;
    r->horizon = horizon;
    return r;
}
void rf_ack_destroy(rf_ack_receiver *r)
{
    if (!r)
        return;
    rf_packet_port port = r->port;
    memset(r, 0, sizeof(*r));
    port.release(port.context, r);
}
bool rf_ack_offer(rf_ack_receiver *r, const void *frame, size_t length,
                  rf_ack_classification classification, int64_t now)
{
    rf_data_view v;
    uint8_t digest[32];
    if (!r || r->exhausted || now < 0 || now > INT64_MAX - r->horizon ||
        (classification != RF_ACK_NEW_DATA && classification != RF_ACK_RETRY_DUPLICATE) ||
        !rf_data_decode(frame, length, r->fragment, &v) || v.flags != 2 ||
        v.session != r->session || v.source != r->peer || v.destination != r->local ||
        !r->port.hash(r->port.context, frame, length, digest))
        return false;
    int found = -1;
    for (unsigned i = 0; i < ACK_CACHE; i++)
        if (r->cache[i].used && be(r->cache[i].header + 16, 4) == v.frame_sequence)
        {
            found = i;
            break;
        }
    if (classification == RF_ACK_RETRY_DUPLICATE)
    {
        if (found < 0 || r->cache[found].expires <= now ||
            memcmp(digest, r->cache[found].digest, 32))
            return false;
    }
    else
    {
        if (found >= 0 || r->queued)
            return false;
        found = r->next;
        r->next = (r->next + 1) % ACK_CACHE;
        memcpy(r->cache[found].header, frame, 40);
        memcpy(r->cache[found].digest, digest, 32);
        r->cache[found].expires = now + r->horizon;
        r->cache[found].used = true;
    }
    if (r->queued)
        return r->pending == found;
    r->queued = true;
    r->pending = found;
    r->due = now + r->turnaround;
    return true;
}
size_t rf_ack_take(rf_ack_receiver *r, int64_t now, uint8_t out[56])
{
    if (!r || !out || !r->queued || r->exhausted || now < r->due)
        return 0;
    r->queued = false;
    ack_entry *e = &r->cache[r->pending];
    if (now >= e->expires)
        return 0;
    memcpy(out, e->header, 40);
    out[3] = 2;
    out[4] = 0;
    out[5] = r->local;
    out[6] = r->peer;
    put(out + 34, be(out + 16, 4));
    put(out + 16, r->sequence);
    out[32] = out[33] = 0;
    if (r->sequence == UINT32_MAX)
        r->exhausted = true;
    else
        r->sequence++;
    return 40;
}
void rf_ack_cancel(rf_ack_receiver *r)
{
    if (!r)
        return;
    r->queued = false;
    memset(r->cache, 0, sizeof(r->cache));
}
bool rf_ack_matches(const void *ack, size_t ack_bytes, const void *data, size_t data_bytes,
                    uint16_t fragment)
{
    rf_data_view v;
    const uint8_t *p = ack;
    if (!p || ack_bytes != 40 || !rf_data_decode(data, data_bytes, fragment, &v) || v.flags != 2 ||
        memcmp(p, "LT", 2) || p[2] != 2 || p[3] != 2 || p[4] || p[5] != v.destination ||
        p[6] != v.source || p[7] != v.content || be(p + 8, 8) != v.session || !be(p + 16, 4) ||
        be(p + 20, 4) != v.message_id || be(p + 24, 2) != v.fragment_index ||
        be(p + 26, 2) != v.fragment_count || be(p + 28, 4) != v.message_bytes || be(p + 32, 2) ||
        be(p + 34, 4) != v.frame_sequence || be(p + 38, 2))
        return false;
    return true;
}
