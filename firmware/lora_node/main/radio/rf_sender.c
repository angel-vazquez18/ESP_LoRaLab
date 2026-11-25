#include "radio/rf_sender.h"
#include "radio/rf_ack.h"
#include "radio/rf_fragments.h"
#include <string.h>

struct rf_sender
{
    rf_packet_port port;
    node_radio *radio;
    rf_secure_session *security;
    rf_faults *faults;
    rf_sender_status status;
    rf_data_view header;
    uint8_t frame[255], maximum_retries;
    size_t length;
    uint16_t fragment;
    uint32_t guard, ack_timeout, tx_timeout, highest_sequence;
    uint64_t session;
    uint8_t source, destination;
    int64_t deadline;
    bool used, pending, ack_requested;
    node_radio_event observation;
};
static uint64_t ceil_div(uint64_t n, uint64_t d) { return (n + d - 1) / d; }
uint32_t rf_radio_airtime_us(const node_radio_settings *s, size_t length)
{
    if (!node_radio_valid_settings(s) || !length || length > 255)
        return 0;
    unsigned sf = s->spreading_factor;
    unsigned ldro = (1U << sf) * 1000U >= 16U * s->bandwidth_hz;
    unsigned payload = 8U + ceil_div(8U * length - 4U * sf + 44U, 4U * (sf - 2U * ldro)) *
                                s->coding_rate_denominator;
    uint64_t quarters = 4U * (s->preamble_symbols + payload) + 17U;
    return ceil_div(quarters * (1U << sf) * 1000000U, 4U * s->bandwidth_hz);
}
rf_sender *rf_sender_create(rf_packet_port port, node_radio *radio)
{
    if (!port.allocate || !port.release || !radio || !radio->bus.now_us)
        return NULL;
    rf_sender *s = port.allocate(port.context, sizeof(*s));
    if (!s)
        return NULL;
    memset(s, 0, sizeof(*s));
    s->port = port;
    s->radio = radio;
    return s;
}
static bool active(const rf_sender *s) { return s->used && s->status.state < RF_SENDER_COMPLETED; }
static void finish(rf_sender *s, rf_sender_state state, const char *reason)
{
    if (s->radio->operation || s->radio->event_pending)
    {
        bool stopped = node_radio_stop(s->radio);
        node_radio_event terminal;
        if (!s->pending && node_radio_poll(s->radio, &terminal))
        {
            s->observation = terminal;
            s->pending = true;
        }
        if (!stopped)
        {
            state = RF_SENDER_FAILED;
            reason = "radio_stop_failed";
        }
    }
    s->status.state = state;
    s->status.reason = reason;
}
void rf_sender_cancel(rf_sender *s)
{
    if (s && active(s))
        finish(s, RF_SENDER_CANCELLED, "cancelled");
}
void rf_sender_destroy(rf_sender *s)
{
    if (!s)
        return;
    rf_sender_cancel(s);
    if (s->used)
    {
        node_radio_event ignored;
        node_radio_poll(s->radio, &ignored);
    }
    rf_packet_port port = s->port;
    memset(s, 0, sizeof(*s));
    port.release(port.context, s);
}
bool rf_sender_begin(rf_sender *s, const void *frame, size_t length, uint16_t fragment,
                     uint8_t retries, uint32_t guard, uint32_t turnaround, uint32_t margin,
                     int64_t deadline)
{
    rf_data_view header;
    if (!s || active(s) || s->pending || !s->radio->available || !s->radio->configured ||
        s->radio->operation || s->radio->event_pending || retries > 2 || guard > 1000000U ||
        turnaround > 1000000U || margin > 1000000U ||
        !rf_data_inspect(frame, length, fragment, &header) ||
        (!!(header.flags & 1) != (s->security != NULL)) ||
        (s->security && !rf_secure_ready(s->security)) || (!(header.flags & 2) && retries) ||
        (s->session &&
         (header.session != s->session || header.source != s->source ||
          header.destination != s->destination || header.frame_sequence <= s->highest_sequence)))
        return false;
    int64_t now = s->radio->bus.now_us(s->radio->bus.context);
    if (now < 0 || deadline <= now || deadline - now > INT64_C(3600000000))
        return false;
    uint32_t airtime = rf_radio_airtime_us(&s->radio->applied, length);
    uint32_t ack =
        header.flags & 2
            ? turnaround + rf_radio_airtime_us(&s->radio->applied, s->security ? 56 : 40) + margin
            : 0;
    uint32_t tx = airtime + (margin > 1000U ? margin : 1000U);
    uint64_t worst = (uint64_t)(retries + 1) * (tx + ack + guard);
    if (!airtime || tx > 30000000U || ack > 30000000U || worst > (uint64_t)(deadline - now))
        return false;
    s->session = header.session;
    s->source = header.source;
    s->destination = header.destination;
    s->highest_sequence = header.frame_sequence;
    memcpy(s->frame, frame, length);
    s->length = length;
    s->header = header;
    s->header.body = s->frame + 40;
    s->fragment = fragment;
    s->maximum_retries = retries;
    s->guard = guard;
    s->ack_timeout = ack;
    s->tx_timeout = tx;
    s->deadline = deadline;
    s->ack_requested = header.flags & 2;
    s->used = true;
    s->status =
        (rf_sender_status){.state = RF_SENDER_READY, .last_ack_acceptance = RF_SECURE_REJECTED};
    return true;
}
static void retry(rf_sender *s, int64_t now)
{
    if (!s->ack_requested || s->status.attempts >= 1U + s->maximum_retries)
        finish(s, RF_SENDER_FAILED, "retry_exhausted");
    else
    {
        s->status.state = RF_SENDER_GUARD;
        s->status.retry_at_us = s->deadline - now < s->guard ? s->deadline : now + s->guard;
    }
}
static bool receive(rf_sender *s, int64_t now)
{
    int64_t remaining = s->status.ack_deadline_us - now;
    return remaining > 0 && node_radio_rx(s->radio, s->security ? 56 : 40, remaining);
}
bool rf_sender_security(rf_sender *s, rf_secure_session *owner)
{
    if (!s || s->used || !rf_secure_ready(owner))
        return false;
    s->security = owner;
    return true;
}
bool rf_sender_faults(rf_sender *s, rf_faults *owner)
{
    if (!s || s->used || !owner) return false;
    s->faults = owner;
    return true;
}
static bool accept_ack(void *context, const uint8_t header[40], const uint8_t *body, size_t bytes)
{
    (void)body;
    rf_sender *s = context;
    return !bytes && rf_ack_header_matches(header, s->frame);
}
static bool matching_ack(rf_sender *s, const node_radio_event *event)
{
    if (!s->security)
        return rf_ack_matches(event->bytes, event->frame_bytes, s->frame, s->length, s->fragment);
    s->status.last_ack_acceptance = rf_secure_receive(s->security, event->bytes, event->frame_bytes,
                                                      event->done_us, false, 0, accept_ack, s);
    return s->status.last_ack_acceptance == RF_SECURE_ACCEPTED;
}
static void advance(rf_sender *s)
{
    if (!active(s))
        return;
    int64_t now = s->radio->bus.now_us(s->radio->bus.context);
    if (now >= s->deadline)
    {
        finish(s, RF_SENDER_FAILED, "run_deadline");
        return;
    }
    if (s->pending)
    {
        node_radio_poll(s->radio, NULL);
        return;
    }
    if (s->status.state == RF_SENDER_READY ||
        (s->status.state == RF_SENDER_GUARD && now >= s->status.retry_at_us))
    {
        node_radio_reference ref = {s->header.session, s->header.frame_sequence,
                                    s->header.message_id, s->header.fragment_index,
                                    s->status.attempts + 1};
        uint32_t timeout = s->tx_timeout;
        if (s->deadline - now < timeout)
        {
            finish(s, RF_SENDER_FAILED, "run_deadline");
            return;
        }
        const uint8_t *wire = s->faults ? rf_faults_transform(s->faults, s->frame,
            s->length, s->status.attempts + 1, now) : s->frame;
        if (!wire) finish(s, RF_SENDER_FAILED, "fault_transform_failed");
        else if (!node_radio_tx(s->radio, wire, s->length, &ref, timeout))
            finish(s, RF_SENDER_FAILED, "radio_tx_failed");
        else
        {
            s->status.originals = 1;
            s->status.attempts++;
            s->status.state = RF_SENDER_TX;
        }
        return;
    }
    if (s->status.state == RF_SENDER_GUARD)
        return;
    node_radio_event event;
    if (!node_radio_poll(s->radio, &event))
        return;
    s->observation = event;
    s->pending = true;
    if (s->status.state == RF_SENDER_TX)
    {
        if (event.status != RADIO_DONE)
        {
            if (event.status == RADIO_TIMEOUT && s->radio->available)
                retry(s, now);
            else
                finish(s, RF_SENDER_FAILED, "radio_tx_failed");
        }
        else if (!s->ack_requested)
            finish(s, RF_SENDER_COMPLETED, "completed");
        else
        {
            s->status.ack_deadline_us = s->deadline - event.done_us < s->ack_timeout
                                            ? s->deadline
                                            : event.done_us + s->ack_timeout;
            if (receive(s, now))
                s->status.state = RF_SENDER_ACK;
            else if (now >= s->status.ack_deadline_us)
                retry(s, now);
            else
                finish(s, RF_SENDER_FAILED, "radio_rx_failed");
        }
    }
    else if (s->status.state == RF_SENDER_ACK)
    {
        s->status.last_ack_acceptance = RF_SECURE_REJECTED;
        if (event.status == RADIO_DONE && event.crc_ok && matching_ack(s, &event))
        {
            s->status.acks++;
            finish(s, RF_SENDER_COMPLETED, "acknowledged");
        }
        else if (s->security && s->status.last_ack_acceptance == RF_SECURE_UNAVAILABLE)
            finish(s, RF_SENDER_FAILED, "crypto_unavailable");
        else if (event.status == RADIO_FAILED || !s->radio->available)
            finish(s, RF_SENDER_FAILED, "radio_rx_failed");
        else if (event.status == RADIO_TIMEOUT || now >= s->status.ack_deadline_us)
            retry(s, now);
        else
        {
            s->status.rejected_acks++;
            if (!receive(s, now))
                finish(s, RF_SENDER_FAILED, "radio_rx_failed");
        }
    }
}
bool rf_sender_poll(rf_sender *s, node_radio_event *out)
{
    if (!s)
        return false;
    advance(s);
    if (!active(s) && s->used && !s->pending && node_radio_poll(s->radio, &s->observation))
        s->pending = true;
    if (!s->pending || !out)
        return false;
    *out = s->observation;
    s->pending = false;
    return true;
}
void rf_sender_snapshot(const rf_sender *s, rf_sender_status *out)
{
    if (s && out)
        *out = s->status;
}

void rf_sender_memory(const rf_sender *s, node_memory_inventory *out)
{
    if (!s) return;
    node_memory_add(out, "rf_sender", s, sizeof(*s));
}
