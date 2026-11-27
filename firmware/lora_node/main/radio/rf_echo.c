#include "radio/rf_echo.h"
#include "radio/rf_sender.h"
#include <string.h>

enum { READY, REQUEST_TX, WAIT_REQUEST, WAIT_REPLY, REPLY_DELAY, REPLY_TX, DRAIN, FINISHED };
struct rf_echo
{
    rf_echo_port port;
    rf_message_plan packet;
    const uint8_t *body;
    rf_echo_status status;
    unsigned phase;
    int64_t deadline, wait_until, drain_until, reply_due;
    uint32_t drain_us;
    bool result_pending, have_digest;
    uint8_t frame[255], accepted_digest[32];
    size_t frame_bytes;
    rf_echo_header candidate;
    const char *rejection;
};
static uint64_t read_be(const uint8_t *p, unsigned n)
{
    uint64_t value = 0;
    while (n--) value = value << 8 | *p++;
    return value;
}
static void write_be(uint8_t *p, uint32_t value)
{
    for (unsigned i = 4; i; i--) { p[i - 1] = value; value >>= 8; }
}
static int64_t now(const rf_echo *s) { return s->port.now_us(s->port.memory.context); }
static bool receive(rf_echo *s)
{
    int64_t end = s->phase == DRAIN ? s->drain_until : s->deadline;
    int64_t remaining = end - now(s);
    return remaining > 0 && node_radio_rx(s->port.radio, 255,
                                          remaining > 30000000 ? 30000000 : (uint32_t)remaining);
}
static void fail(rf_echo *s, const char *reason)
{
    if (!s->status.valid) s->status.reason = reason;
    s->status.failed = s->status.done = true;
    s->phase = FINISHED;
    if (s->status.requester && !s->status.valid) s->result_pending = true;
}
static void drain(rf_echo *s)
{
    s->phase = DRAIN;
    s->drain_until = now(s) + s->drain_us;
    if (s->drain_until > s->deadline) s->drain_until = s->deadline;
}
static bool build(rf_echo *s, bool reply)
{
    rf_message_plan p = s->packet;
    if (reply)
    {
        p.source = s->packet.destination;
        p.destination = s->packet.source;
        uint32_t sequence = 1;
        if (s->port.security && rf_secure_reserve(s->port.security, 1, &sequence) != RF_CRYPTO_OK)
            return false;
        p.first_sequence = s->status.reply_sequence = sequence;
    }
    uint8_t header[40];
    if (!rf_message_header(&p, 0, header)) return false;
    header[3] = reply ? 4 : 3;
    if (reply) write_be(header + 34, s->status.request_sequence);
    if (p.flags & 1)
        return rf_secure_seal(s->port.security, header, s->body, p.message_bytes, s->frame,
                               sizeof(s->frame), &s->frame_bytes) == RF_CRYPTO_OK;
    memcpy(s->frame, header, 40);
    memcpy(s->frame + 40, s->body, p.message_bytes);
    s->frame_bytes = 40 + p.message_bytes;
    return true;
}
static bool transmit(rf_echo *s, bool reply)
{
    if (!build(s, reply)) return false;
    node_radio_reference reference = {s->packet.session,
        reply ? s->status.reply_sequence : s->status.request_sequence, s->packet.message_id, 0, 1};
    uint32_t timeout = rf_radio_airtime_us(&s->port.radio->applied, s->frame_bytes) + 80000;
    if (!node_radio_tx(s->port.radio, s->frame, s->frame_bytes, &reference, timeout)) return false;
    s->status.attempts++;
    s->phase = reply ? REPLY_TX : REQUEST_TX;
    return true;
}
static bool inspect(rf_echo *s, const uint8_t *frame, size_t bytes, rf_echo_header *out)
{
    if (bytes <= 40 || bytes > 255 || (frame[3] != 3 && frame[3] != 4)) return false;
    uint32_t reference = read_be(frame + 34, 4);
    if ((frame[3] == 3 && reference) || (frame[3] == 4 && !reference)) return false;
    rf_message_plan p;
    if (!rf_message_plan_init(&p, read_be(frame + 8, 8), read_be(frame + 16, 4),
        read_be(frame + 20, 4), frame[5], frame[6], 0, frame[4] & 1, false,
        read_be(frame + 28, 4), s->packet.fragment_bytes) || p.fragment_count != 1 ||
        bytes != 40U + p.message_bytes + ((p.flags & 1) ? 16U : 0U)) return false;
    uint8_t expected[40];
    rf_message_header(&p, 0, expected);
    expected[3] = frame[3];
    write_be(expected + 34, reference);
    if (memcmp(expected, frame, 40)) return false;
    *out = (rf_echo_header){p.session, p.first_sequence, p.message_id, reference,
        p.message_bytes, p.source, p.destination, frame[3]};
    return true;
}
static bool validate(void *context, const uint8_t header[40], const uint8_t *body, size_t bytes)
{
    rf_echo *s = context;
    (void)header;
    if (s->candidate.message != s->packet.message_id || bytes != s->packet.message_bytes)
        s->rejection = "wrong_message";
    else if (s->status.requester && s->candidate.reference != s->status.request_sequence)
        s->rejection = "wrong_reference";
    else if (memcmp(body, s->body, bytes)) s->rejection = "content_mismatch";
    else if (s->status.requester && s->status.valid)
        s->rejection = s->candidate.sequence == s->status.reply_sequence ? "duplicate" : "unexpected_reply";
    else if (!s->status.requester && s->status.request_seen)
        s->rejection = s->candidate.sequence == s->status.request_sequence ? "duplicate" : "unexpected_request";
    else if (s->phase == DRAIN || s->phase == FINISHED ||
             (s->status.requester && now(s) >= s->wait_until)) s->rejection = "late";
    else if (s->status.requester && s->status.tx_command_us < 0) s->rejection = "missing_tx_command";
    if (!s->rejection && s->status.requester) memcpy(s->frame, body, bytes);
    return s->rejection == NULL;
}
static void received(rf_echo *s, rf_echo_event *out)
{
    node_radio_event *event = &out->radio;
    s->rejection = NULL;
    out->decoded = event->status == RADIO_DONE && event->crc_ok &&
        inspect(s, event->bytes, event->frame_bytes, &s->candidate);
    out->header = s->candidate;
    if (!out->decoded) s->rejection = "invalid_frame";
    else if (s->candidate.session != s->packet.session) s->rejection = "wrong_session";
    else if (s->candidate.source != (s->status.requester ? s->packet.destination : s->packet.source) ||
             s->candidate.destination != (s->status.requester ? s->packet.source : s->packet.destination))
        s->rejection = "wrong_source";
    else if (s->candidate.type != (s->status.requester ? 4 : 3)) s->rejection = "unexpected_frame";
    else if ((event->bytes[4] & 1) != (s->packet.flags & 1)) s->rejection = "protection_mismatch";
    else if (s->port.security)
    {
        rf_secure_acceptance result = rf_secure_receive(s->port.security, event->bytes,
            event->frame_bytes, now(s), false, 0, validate, s);
        if (result != RF_SECURE_ACCEPTED && !s->rejection)
        {
            uint8_t digest[32];
            bool same = s->have_digest && s->port.memory.hash(s->port.memory.context,
                event->bytes, event->frame_bytes, digest) && !memcmp(digest, s->accepted_digest, 32);
            s->rejection = result == RF_SECURE_AUTH_FAILED ? "authentication_failed" :
                result == RF_SECURE_REPLAY ? same ? "duplicate" : "replay" :
                result == RF_SECURE_TOO_OLD ? "too_old" : "invalid_frame";
        }
    }
    else validate(s, event->bytes, event->bytes + 40, s->candidate.bytes);
    if (s->rejection) { out->rejection = s->rejection; return; }
    out->accepted = true;
    out->accepted_us = now(s);
    s->have_digest = s->port.memory.hash(s->port.memory.context, event->bytes,
                                         event->frame_bytes, s->accepted_digest);
    if (s->status.requester)
    {
        s->status.reply_sequence = s->candidate.sequence;
        s->status.accepted_us = out->accepted_us;
        s->status.valid = true;
        s->status.reason = "matched";
        s->result_pending = true;
        drain(s);
    }
    else
    {
        s->status.request_seen = true;
        s->status.request_sequence = s->candidate.sequence;
        s->status.reason = "reply_pending";
        s->reply_due = now(s) + 20000;
        s->phase = REPLY_DELAY;
    }
}
rf_echo *rf_echo_create(rf_echo_port port, const rf_message_plan *packet, const uint8_t *body,
                        bool requester, uint32_t drain_us)
{
    if (!packet || !body || packet->fragment_count != 1 || packet->content || packet->flags & 2 ||
        !port.memory.allocate || !port.memory.release || !port.memory.hash || !port.now_us ||
        !port.radio || ((packet->flags & 1) && !rf_secure_ready(port.security))) return NULL;
    rf_echo *s = port.memory.allocate(port.memory.context, sizeof(*s));
    if (!s) return NULL;
    *s = (rf_echo){.port = port, .packet = *packet, .body = body, .drain_us = drain_us,
        .status = {.requester = requester, .request_sequence = requester ? packet->first_sequence : 0,
            .tx_command_us = -1, .accepted_us = -1, .reason = "not_started"}};
    return s;
}
bool rf_echo_arm(rf_echo *s, int64_t deadline)
{
    if (!s || s->status.requester || s->phase != READY || deadline <= now(s)) return false;
    s->deadline = deadline;
    s->phase = WAIT_REQUEST;
    s->status.reason = "waiting_request";
    return receive(s);
}
bool rf_echo_start(rf_echo *s, int64_t deadline)
{
    if (!s || !s->status.requester || s->phase != READY || deadline - now(s) <= s->drain_us) return false;
    s->deadline = deadline;
    s->wait_until = deadline - s->drain_us;
    s->status.reason = "waiting_reply";
    return transmit(s, false);
}
void rf_echo_poll(rf_echo *s, rf_echo_event *out)
{
    *out = (rf_echo_event){0};
    if (!s || s->phase == READY || s->phase == FINISHED) return;
    int64_t time = now(s);
    if (s->status.requester && !s->status.valid && s->phase != DRAIN && time >= s->wait_until)
    {
        s->status.reason = "timeout";
        s->status.failed = true;
        s->result_pending = true;
        drain(s);
    }
    if ((s->phase == DRAIN && time >= s->drain_until) || time >= s->deadline)
    {
        if (!s->status.request_seen && !s->status.requester) fail(s, "timeout");
        s->status.done = true;
        s->phase = FINISHED;
    }
    else if (s->phase == REPLY_DELAY && time >= s->reply_due)
    {
        if (!transmit(s, true)) fail(s, "tx_failed");
    }
    else if (s->phase != REPLY_DELAY && node_radio_poll(s->port.radio, &out->radio))
    {
        out->observed = true;
        if (out->radio.kind == RADIO_EVENT_TX)
        {
            if (out->radio.status != RADIO_DONE) fail(s, "tx_failed");
            else
            {
                if (s->status.requester)
                {
                    s->status.tx_command_us = out->radio.command_us;
                    if (s->phase != DRAIN) s->phase = WAIT_REPLY;
                }
                else { s->status.reason = "reply_sent"; drain(s); }
                if (!receive(s)) fail(s, "rx_failed");
            }
        }
        else if (out->radio.status == RADIO_TIMEOUT)
        {
            if (!receive(s)) fail(s, "rx_failed");
        }
        else
        {
            received(s, out);
            if (s->phase != REPLY_DELAY && !receive(s)) fail(s, "rx_failed");
        }
    }
    out->result_ready = s->result_pending;
    s->result_pending = false;
}
void rf_echo_abort(rf_echo *s, const char *reason) { if (s && !s->status.done) fail(s, reason); }
const uint8_t *rf_echo_reply(const rf_echo *s, size_t *bytes)
{
    *bytes = s && s->status.requester && s->status.valid ? s->packet.message_bytes : 0;
    return *bytes ? s->frame : NULL;
}
void rf_echo_snapshot(const rf_echo *s, rf_echo_status *out) { *out = s->status; }
void rf_echo_destroy(rf_echo *s)
{
    if (!s) return;
    rf_echo_port port = s->port;
    volatile uint8_t *bytes = (volatile uint8_t *)s;
    for (size_t i = 0; i < sizeof(*s); i++) bytes[i] = 0;
    port.memory.release(port.memory.context, s);
}
void rf_echo_memory(const rf_echo *s, node_memory_inventory *out)
{
    if (s) node_memory_add(out, "rf_echo_pending", s, sizeof(*s));
}
