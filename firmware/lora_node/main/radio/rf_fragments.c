#include "radio/rf_fragments.h"
#include <string.h>

static void be(uint8_t *out, uint64_t value, unsigned size)
{
    while (size)
    {
        out[--size] = (uint8_t)value;
        value >>= 8;
    }
}
bool rf_message_plan_init(rf_message_plan *out, uint64_t session, uint32_t sequence,
                          uint32_t message, uint8_t source, uint8_t destination, uint8_t content,
                          bool protected_frame, bool ack, uint32_t bytes, uint16_t fragment)
{
    unsigned capacity = protected_frame ? 199U : 215U;
    if (!out || !session || !sequence || !message || !bytes || bytes > RF_MESSAGE_BYTES ||
        (source != 1 && source != 2) || (destination != 1 && destination != 2) ||
        source == destination || content > 1 || fragment < 16 || fragment > capacity)
        return false;
    uint32_t count = (bytes + fragment - 1) / fragment;
    if (count > RF_MESSAGE_FRAGMENTS || count - 1 > UINT32_MAX - sequence)
        return false;
    *out = (rf_message_plan){.session = session,
                             .first_sequence = sequence,
                             .message_id = message,
                             .message_bytes = bytes,
                             .fragment_bytes = fragment,
                             .fragment_count = count,
                             .source = source,
                             .destination = destination,
                             .content = content,
                             .flags = (protected_frame ? 1 : 0) | (ack ? 2 : 0)};
    return true;
}
static bool valid(const rf_message_plan *p, uint16_t index)
{
    rf_message_plan expected;
    return p && !(p->flags & ~3U) && index < p->fragment_count &&
           rf_message_plan_init(&expected, p->session, p->first_sequence, p->message_id, p->source,
                                p->destination, p->content, p->flags & 1, p->flags & 2,
                                p->message_bytes, p->fragment_bytes) &&
           expected.fragment_count == p->fragment_count;
}
static uint16_t body_bytes(const rf_message_plan *p, uint16_t index)
{
    uint32_t remaining = p->message_bytes - (uint32_t)index * p->fragment_bytes;
    return remaining < p->fragment_bytes ? remaining : p->fragment_bytes;
}
size_t rf_message_header(const rf_message_plan *p, uint16_t index, uint8_t out[40])
{
    if (!out || !valid(p, index))
        return 0;
    memset(out, 0, 40);
    out[0] = 'L';
    out[1] = 'T';
    out[2] = 2;
    out[3] = 1;
    out[4] = p->flags;
    out[5] = p->source;
    out[6] = p->destination;
    out[7] = p->content;
    be(out + 8, p->session, 8);
    be(out + 16, p->first_sequence + index, 4);
    be(out + 20, p->message_id, 4);
    be(out + 24, index, 2);
    be(out + 26, p->fragment_count, 2);
    be(out + 28, p->message_bytes, 4);
    be(out + 32, body_bytes(p, index), 2);
    return 40;
}
size_t rf_message_fragment(const rf_message_plan *p, uint16_t index, const void *source,
                           size_t source_bytes, uint8_t out[255])
{
    if (!source || !out || !valid(p, index) || (p->flags & 1) || source_bytes != p->message_bytes)
        return 0;
    rf_message_header(p, index, out);
    size_t size = body_bytes(p, index);
    memcpy(out + 40, (const uint8_t *)source + (uint32_t)index * p->fragment_bytes, size);
    return 40 + size;
}

static uint64_t read_be(const uint8_t *p, unsigned size)
{
    uint64_t value = 0;
    while (size--)
        value = (value << 8) | *p++;
    return value;
}
bool rf_data_inspect(const void *frame, size_t length, uint16_t fragment, rf_data_view *out)
{
    const uint8_t *p = frame;
    if (!p || !out || length <= 40 || length > 255 || memcmp(p, "LT", 2) || p[2] != 2 ||
        p[3] != 1 || p[4] & ~3U || p[7] > 1 || !read_be(p + 16, 4) || read_be(p + 34, 4) ||
        read_be(p + 38, 2))
        return false;
    rf_message_plan plan;
    if (!rf_message_plan_init(&plan, read_be(p + 8, 8), 1, read_be(p + 20, 4), p[5], p[6], p[7],
                              p[4] & 1, p[4] & 2, read_be(p + 28, 4), fragment))
        return false;
    uint16_t index = read_be(p + 24, 2);
    if (read_be(p + 26, 2) != plan.fragment_count || index >= plan.fragment_count ||
        read_be(p + 32, 2) != body_bytes(&plan, index) ||
        length != 40U + body_bytes(&plan, index) + ((p[4] & 1) ? 16U : 0U))
        return false;
    *out = (rf_data_view){.session = plan.session,
                          .frame_sequence = read_be(p + 16, 4),
                          .message_id = plan.message_id,
                          .message_bytes = plan.message_bytes,
                          .fragment_index = index,
                          .fragment_count = plan.fragment_count,
                          .body_bytes = body_bytes(&plan, index),
                          .source = plan.source,
                          .destination = plan.destination,
                          .content = plan.content,
                          .flags = plan.flags,
                          .body = (p[4] & 1) ? NULL : p + 40};
    return true;
}

bool rf_data_decode(const void *frame, size_t length, uint16_t fragment, rf_data_view *out)
{
    rf_data_view candidate;
    if (!out || !rf_data_inspect(frame, length, fragment, &candidate) || (candidate.flags & 1))
        return false;
    *out = candidate;
    return true;
}
