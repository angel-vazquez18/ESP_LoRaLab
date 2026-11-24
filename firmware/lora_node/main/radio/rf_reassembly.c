#include "radio/rf_reassembly.h"
#include "radio/rf_fragments.h"
#include <string.h>

struct rf_reassembly
{
    rf_reassembly_port port;
    uint64_t session;
    uint32_t message, highest_message, bytes;
    uint16_t fragment, count, received;
    uint8_t source, destination, content, flags;
    bool active, complete, taken;
    int64_t deadline;
    rf_reassembly_result outcome;
    uint8_t expected[32], digest[32], present[RF_MESSAGE_FRAGMENTS / 8];
    uint8_t *data;
};
static uint64_t be(const uint8_t *p, unsigned size)
{
    uint64_t v = 0;
    while (size--)
        v = (v << 8) | *p++;
    return v;
}
static bool present(const rf_reassembly *r, unsigned index)
{
    return (r->present[index / 8] & (1U << (index % 8))) != 0;
}
static void release(rf_reassembly *r)
{
    if (r->data)
    {
        memset(r->data, 0, r->bytes);
        r->port.release(r->port.context, r->data);
        r->data = NULL;
    }
}
static rf_reassembly_result fail(rf_reassembly *r, rf_reassembly_result result)
{
    release(r);
    r->active = r->complete = false;
    return r->outcome = result;
}
rf_reassembly *rf_reassembly_create(rf_reassembly_port port, uint64_t session, uint8_t source,
                                    uint8_t destination, uint16_t fragment)
{
    rf_message_plan plan;
    if (!port.allocate || !port.release || !port.hash ||
        !rf_message_plan_init(&plan, session, 1, 1, source, destination, 0, false, false, 1,
                              fragment))
        return NULL;
    rf_reassembly *r = port.allocate(port.context, sizeof(*r));
    if (!r)
        return NULL;
    memset(r, 0, sizeof(*r));
    r->port = port;
    r->session = session;
    r->source = source;
    r->destination = destination;
    r->fragment = fragment;
    return r;
}
void rf_reassembly_destroy(rf_reassembly *r)
{
    if (!r)
        return;
    release(r);
    rf_reassembly_port port = r->port;
    memset(r, 0, sizeof(*r));
    port.release(port.context, r);
}
bool rf_reassembly_begin(rf_reassembly *r, uint32_t message, uint8_t content, uint8_t flags,
                         uint32_t bytes, const uint8_t digest[32], int64_t now, int64_t deadline)
{
    rf_message_plan p;
    if (!r || r->active || !digest || message <= r->highest_message || flags & ~3U || now < 0 ||
        deadline <= now || deadline - now > INT64_C(3600000000) ||
        !rf_message_plan_init(&p, r->session, 1, message, r->source, r->destination, content,
                              flags & 1, flags & 2, bytes, r->fragment))
        return false;
    /* Release a previously delivered buffer before reserving the next one. */
    release(r);
    r->complete = r->taken = false;
    uint8_t *buffer = r->port.allocate(r->port.context, bytes);
    if (!buffer)
        return false;
    r->data = buffer;
    r->bytes = bytes;
    r->message = r->highest_message = message;
    r->count = p.fragment_count;
    r->content = content;
    r->flags = flags;
    r->deadline = deadline;
    r->received = 0;
    r->active = true;
    r->outcome = RF_REASSEMBLY_ACCEPTED;
    memset(r->present, 0, sizeof(r->present));
    memcpy(r->expected, digest, 32);
    return true;
}
rf_reassembly_result rf_reassembly_poll(rf_reassembly *r, int64_t now)
{
    if (!r || now < 0)
        return RF_REASSEMBLY_REJECTED;
    if (r->active && now >= r->deadline)
        return fail(r, RF_REASSEMBLY_EXPIRED);
    return r->outcome;
}
static rf_reassembly_result accept(rf_reassembly *r, const uint8_t *p, const uint8_t *plain,
                                   size_t body_bytes, bool authenticated, int64_t now)
{
    size_t length = 40 + body_bytes + (authenticated ? 16 : 0);
    if (!r || !p || !plain || body_bytes > (authenticated ? 199U : 215U) ||
        !!(p[4] & 1) != authenticated || now < 0 || length <= 40 || length > 255 ||
        memcmp(p, "LT", 2) || p[2] != 2 || p[3] != 1 || p[4] & ~3U || p[7] > 1 || !be(p + 16, 4) ||
        !be(p + 20, 4) || be(p + 34, 4) || be(p + 38, 2))
        return RF_REASSEMBLY_REJECTED;
    if (be(p + 8, 8) != r->session || p[5] != r->source || p[6] != r->destination)
        return RF_REASSEMBLY_REJECTED;
    uint32_t message = be(p + 20, 4);
    if (message != r->message)
        return message <= r->highest_message ? RF_REASSEMBLY_STALE : RF_REASSEMBLY_REJECTED;
    if (r->active && rf_reassembly_poll(r, now) == RF_REASSEMBLY_EXPIRED)
        return RF_REASSEMBLY_EXPIRED;
    if (!r->active && !r->complete)
        return RF_REASSEMBLY_STALE;
    unsigned index = be(p + 24, 2), count = be(p + 26, 2), body = be(p + 32, 2);
    if (p[4] != r->flags || p[7] != r->content || be(p + 28, 4) != r->bytes || count != r->count ||
        index >= count ||
        body != (index + 1 < count ? r->fragment : r->bytes - index * r->fragment) ||
        body_bytes != body)
        return r->complete ? RF_REASSEMBLY_CONFLICT : fail(r, RF_REASSEMBLY_CONFLICT);
    uint8_t *destination = r->data + index * r->fragment;
    if (present(r, index))
    {
        if (memcmp(destination, plain, body))
            return r->complete ? RF_REASSEMBLY_CONFLICT : fail(r, RF_REASSEMBLY_CONFLICT);
        return RF_REASSEMBLY_DUPLICATE;
    }
    memcpy(destination, plain, body);
    r->present[index / 8] |= 1U << (index % 8);
    r->received++;
    if (r->received < r->count)
        return RF_REASSEMBLY_ACCEPTED;
    if (!r->port.hash(r->port.context, r->data, r->bytes, r->digest) ||
        memcmp(r->digest, r->expected, 32))
        return fail(r, RF_REASSEMBLY_HASH_FAILED);
    r->active = false;
    r->complete = true;
    return r->outcome = RF_REASSEMBLY_COMPLETE;
}
void rf_reassembly_cancel(rf_reassembly *r)
{
    if (r)
        fail(r, RF_REASSEMBLY_CANCELLED);
}
size_t rf_reassembly_missing(const rf_reassembly *r, uint16_t first, uint16_t *out, size_t capacity)
{
    if (!r || !out)
        return 0;
    size_t written = 0;
    for (unsigned i = first; i < r->count && written < capacity; i++)
        if (!present(r, i))
            out[written++] = i;
    return written;
}
bool rf_reassembly_take(rf_reassembly *r, const void **bytes, size_t *length, uint8_t digest[32])
{
    if (!r || !bytes || !length || !digest || !r->complete || r->taken)
        return false;
    *bytes = r->data;
    *length = r->bytes;
    memcpy(digest, r->digest, 32);
    r->taken = true;
    return true;
}

rf_reassembly_result rf_reassembly_accept(rf_reassembly *r, const void *input, size_t length,
                                          int64_t now)
{
    const uint8_t *frame = input;
    if (!frame || length <= 40 || length > 255)
        return RF_REASSEMBLY_REJECTED;
    return accept(r, frame, frame + 40, length - 40, false, now);
}
rf_reassembly_result rf_reassembly_accept_authenticated(rf_reassembly *r, const uint8_t header[40],
                                                        const uint8_t *body, size_t bytes,
                                                        int64_t now)
{
    return accept(r, header, body, bytes, true, now);
}
