#include "radio/rf_frames.h"
#include "radio/rf_fragments.h"
#include <string.h>

static void write_be(uint8_t *p, uint64_t n, unsigned count)
{
    while (count)
    {
        p[--count] = (uint8_t)n;
        n >>= 8;
    }
}
size_t rf_single_encode(uint64_t session, uint32_t sequence, uint32_t message, uint8_t source,
                        uint8_t destination, const void *body, size_t length, uint8_t out[255])
{
    rf_message_plan plan;
    if (length > RF_SINGLE_BYTES ||
        !rf_message_plan_init(&plan, session, sequence, message, source, destination, 0, false,
                              false, length, RF_SINGLE_BYTES))
        return 0;
    return rf_message_fragment(&plan, 0, body, length, out);
}

bool rf_single_decode(const uint8_t *bytes, size_t length, uint32_t fragment, rf_single_header *out)
{
    rf_data_view v;
    if (!out || fragment > RF_SINGLE_BYTES || !rf_data_decode(bytes, length, fragment, &v) ||
        v.flags || v.content || v.fragment_count != 1)
        return false;
    *out = (rf_single_header){.session = v.session,
                              .frame_seq = v.frame_sequence,
                              .message_id = v.message_id,
                              .message_bytes = v.message_bytes,
                              .source = v.source,
                              .destination = v.destination};
    return true;
}

bool rf_known_data(rf_hash hash, void *context, uint32_t seed, uint32_t message, void *output,
                   size_t length)
{
    if (!hash || !output || !message || !length || length > 65536)
        return false;
    uint8_t input[27], digest[32];
    memcpy(input, "lora-testbed-v2", 15);
    write_be(input + 15, seed, 4);
    write_be(input + 19, message, 4);
    uint8_t *out = output;
    for (uint32_t block = 0; length; block++)
    {
        write_be(input + 23, block, 4);
        if (!hash(context, input, sizeof(input), digest))
            return false;
        size_t take = length < 32 ? length : 32;
        memcpy(out, digest, take);
        out += take;
        length -= take;
    }
    return true;
}
rf_acceptance rf_single_accept(rf_single_receiver *receiver, const uint8_t *bytes, size_t length,
                               uint32_t fragment, rf_hash hash, void *context, uint8_t output[215],
                               uint8_t digest[32])
{
    rf_single_header h;
    if (!receiver || !output || !digest || !rf_single_decode(bytes, length, fragment, &h))
        return RF_INVALID_FRAME;
    if (h.session != receiver->session)
        return RF_WRONG_SESSION;
    if (h.source != receiver->source || h.destination != receiver->destination)
        return RF_WRONG_ROLE;
    if (h.message_id > receiver->message_count || h.message_bytes != receiver->message_bytes)
        return RF_WRONG_MESSAGE;
    uint8_t expected[215], actual_digest[32];
    if (!rf_known_data(hash, context, receiver->seed, h.message_id, expected, h.message_bytes))
        return RF_INTERNAL_ERROR;
    if (memcmp(expected, bytes + 40, h.message_bytes))
        return RF_CONTENT_MISMATCH;
    if (h.message_id == receiver->highest_message)
        return RF_DUPLICATE;
    if (h.message_id < receiver->highest_message || h.frame_seq <= receiver->highest_sequence)
        return RF_STALE;
    if (!hash(context, bytes + 40, h.message_bytes, actual_digest))
        return RF_INTERNAL_ERROR;
    memcpy(output, bytes + 40, h.message_bytes);
    memcpy(digest, actual_digest, 32);
    receiver->highest_message = h.message_id;
    receiver->highest_sequence = h.frame_seq;
    return RF_DELIVERED;
}
