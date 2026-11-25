#include "radio/rf_faults.h"
#include <string.h>

struct rf_faults {
    rf_packet_port port;
    uint64_t session;
    uint8_t source, maximum_attempts;
    bool prepared;
    unsigned count, queued, head;
    rf_message_plan packet;
    struct { rf_fault_view view; unsigned slot; } entries[RF_FAULT_ENTRIES];
    rf_fault_view events[RF_FAULT_ENTRIES];
    uint8_t retained[RF_FAULT_RETAINED][255], scratch[255];
};
static void wipe(void *pointer, size_t bytes)
{
    volatile uint8_t *out = pointer;
    while (bytes--) *out++ = 0;
}
static bool identifier(const char id[37])
{
    if (id[36]) return false;
    for (unsigned i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) { if (id[i] != '-') return false; }
        else if (!((id[i] >= '0' && id[i] <= '9') || (id[i] >= 'a' && id[i] <= 'f')))
            return false;
    }
    return true;
}
static bool valid_spec(const rf_fault_spec *spec)
{
    if (!identifier(spec->id) || !spec->message || !spec->attempt || spec->attempt > 3 ||
        spec->fragment >= RF_MESSAGE_FRAGMENTS) return false;
    if (spec->action == RF_FAULT_XOR)
        return spec->offset >= RF_HEADER_BYTES && spec->offset < 255 && spec->mask;
    return spec->action == RF_FAULT_REPLAY && !spec->offset && !spec->mask;
}
static bool fits(const rf_fault_spec *spec, const rf_message_plan *p, unsigned attempts)
{
    if (!(p->flags & 1) || spec->message != p->message_id ||
        spec->fragment >= p->fragment_count || spec->attempt > attempts) return false;
    uint32_t offset = (uint32_t)spec->fragment * p->fragment_bytes;
    uint32_t body = p->message_bytes - offset;
    if (body > p->fragment_bytes) body = p->fragment_bytes;
    return spec->action != RF_FAULT_XOR || spec->offset < RF_HEADER_BYTES + body + RF_TAG_BYTES;
}
rf_faults *rf_faults_create(rf_packet_port port, uint64_t session, uint8_t source)
{
    if (!port.allocate || !port.release || !port.hash || !session ||
        (source != 1 && source != 2)) return NULL;
    rf_faults *s = port.allocate(port.context, sizeof(*s));
    if (s) *s = (rf_faults){.port = port, .session = session, .source = source};
    return s;
}
void rf_faults_destroy(rf_faults *s)
{
    if (!s) return;
    rf_packet_port port = s->port;
    wipe(s, sizeof(*s));
    port.release(port.context, s);
}
bool rf_faults_can_configure(const rf_faults *s, const rf_fault_spec *specs, size_t count, bool replace)
{
    if (!s || count > RF_FAULT_BATCH || (count && !specs) ||
        count + (replace ? 0 : s->count) > RF_FAULT_ENTRIES) return false;
    unsigned keep = replace ? 0 : s->count, replay = 0;
    for (unsigned i = 0; i < keep; i++) replay += s->entries[i].view.spec.action == RF_FAULT_REPLAY;
    for (size_t i = 0; i < count; i++) {
        if (!valid_spec(&specs[i]) ||
            (s->prepared && (s->packet.source != s->source || !fits(&specs[i], &s->packet, s->maximum_attempts)))) return false;
        replay += specs[i].action == RF_FAULT_REPLAY;
        if (replay > RF_FAULT_RETAINED) return false;
        for (size_t j = 0; j < keep + i; j++) {
            const rf_fault_spec *prior = j < keep ? &s->entries[j].view.spec : &specs[j - keep];
            if (!strcmp(prior->id, specs[i].id) ||
                (prior->action == RF_FAULT_XOR && specs[i].action == RF_FAULT_XOR &&
                 prior->message == specs[i].message && prior->fragment == specs[i].fragment &&
                 prior->attempt == specs[i].attempt && prior->offset == specs[i].offset)) return false;
        }
    }
    return true;
}
bool rf_faults_configure(rf_faults *s, const rf_fault_spec *specs, size_t count, bool replace)
{
    if (!rf_faults_can_configure(s, specs, count, replace)) return false;
    unsigned keep = replace ? 0 : s->count;
    if (replace) {
        wipe(s->entries, sizeof(s->entries));
        wipe(s->retained, sizeof(s->retained));
        wipe(s->scratch, sizeof(s->scratch));
        wipe(s->events, sizeof(s->events));
        s->head = s->queued = 0;
    }
    s->count = keep;
    unsigned slot = 0;
    for (unsigned i = 0; i < keep; i++) slot += s->entries[i].view.spec.action == RF_FAULT_REPLAY;
    for (size_t i = 0; i < count; i++) {
        unsigned index = s->count++;
        s->entries[index].view = (rf_fault_view){.spec = specs[i], .applied_us = -1};
        s->entries[index].slot = specs[i].action == RF_FAULT_REPLAY ? slot++ : RF_FAULT_RETAINED;
    }
    return true;
}
bool rf_faults_validate(const rf_faults *s, const rf_message_plan *packet, uint8_t attempts)
{
    if (!s || !packet || !attempts || attempts > 3 || packet->session != s->session ||
        packet->content || (s->count && packet->source != s->source)) return false;
    rf_message_plan checked;
    if (!rf_message_plan_init(&checked, packet->session, packet->first_sequence, packet->message_id,
        packet->source, packet->destination, packet->content, packet->flags & 1, packet->flags & 2,
        packet->message_bytes, packet->fragment_bytes) || checked.fragment_count != packet->fragment_count ||
        checked.flags != packet->flags) return false;
    for (unsigned i = 0; i < s->count; i++)
        if (!fits(&s->entries[i].view.spec, packet, attempts)) return false;
    return true;
}
bool rf_faults_prepare(rf_faults *s, const rf_message_plan *packet, uint8_t attempts)
{
    if (!rf_faults_validate(s, packet, attempts)) return false;
    s->packet = *packet;
    s->maximum_attempts = attempts;
    s->prepared = true;
    return true;
}
static bool hash(rf_faults *s, const void *wire, size_t bytes, uint8_t digest[32])
{
    return s->port.hash(s->port.context, wire, bytes, digest);
}
static void queue(rf_faults *s, const rf_fault_view *view)
{
    // Each of at most 32 entries emits once, so unread events cannot overflow.
    if (s->queued == RF_FAULT_ENTRIES) return;
    s->events[(s->head + s->queued++) % RF_FAULT_ENTRIES] = *view;
}
const uint8_t *rf_faults_transform(rf_faults *s, const uint8_t *wire, size_t bytes,
                                   uint8_t attempt, int64_t now)
{
    if (!s || !s->prepared || !wire || bytes > 255 || now < 0 ||
        !attempt || attempt > s->maximum_attempts) return NULL;
    rf_data_view h;
    if (!rf_data_inspect(wire, bytes, s->packet.fragment_bytes, &h)) return NULL;
    if (!s->count || h.session != s->session || h.source != s->source ||
        h.message_id != s->packet.message_id ||
        h.frame_sequence != s->packet.first_sequence + h.fragment_index) return wire;
    memcpy(s->scratch, wire, bytes);
    for (unsigned i = 0; i < s->count; i++) {
        rf_fault_view *view = &s->entries[i].view;
        const rf_fault_spec *spec = &view->spec;
        if (view->state != RF_FAULT_PLANNED || spec->message != h.message_id ||
            spec->fragment != h.fragment_index || spec->attempt != attempt ||
            spec->action != RF_FAULT_XOR) continue;
        if (spec->offset >= bytes || !hash(s, s->scratch, bytes, view->before)) return NULL;
        s->scratch[spec->offset] ^= spec->mask;
        if (!hash(s, s->scratch, bytes, view->after)) return NULL;
        view->state = RF_FAULT_APPLIED;
        view->sequence = h.frame_sequence;
        view->frame_bytes = bytes;
        view->applied_us = now;
        queue(s, view);
    }
    for (unsigned i = 0; i < s->count; i++) {
        rf_fault_view *view = &s->entries[i].view;
        const rf_fault_spec *spec = &view->spec;
        if (view->state != RF_FAULT_PLANNED || spec->action != RF_FAULT_REPLAY ||
            spec->message != h.message_id || spec->fragment != h.fragment_index ||
            spec->attempt != attempt) continue;
        if (!hash(s, s->scratch, bytes, view->before)) return NULL;
        memcpy(view->after, view->before, 32);
        memcpy(s->retained[s->entries[i].slot], s->scratch, bytes);
        view->sequence = h.frame_sequence;
        view->frame_bytes = bytes;
        view->state = RF_FAULT_READY;
    }
    return s->scratch;
}
const uint8_t *rf_faults_replay(rf_faults *s, const char *id, size_t *bytes)
{
    *bytes = 0;
    if (!s || !id || !s->prepared) return NULL;
    for (unsigned i = 0; i < s->count; i++) {
        rf_fault_view *view = &s->entries[i].view;
        if (!strcmp(id, view->spec.id) && view->state == RF_FAULT_READY) {
            *bytes = view->frame_bytes;
            return s->retained[s->entries[i].slot];
        }
    }
    return NULL;
}
bool rf_faults_fired(rf_faults *s, const char *id, int64_t now)
{
    size_t bytes;
    if (now < 0 || !rf_faults_replay(s, id, &bytes)) return false;
    for (unsigned i = 0; i < s->count; i++) {
        rf_fault_view *view = &s->entries[i].view;
        if (!strcmp(id, view->spec.id)) {
            view->state = RF_FAULT_FIRED;
            view->applied_us = now;
            queue(s, view);
            return true;
        }
    }
    return false;
}
bool rf_faults_pop(rf_faults *s, rf_fault_view *out)
{
    if (!s || !s->queued || !out) return false;
    *out = s->events[s->head];
    wipe(&s->events[s->head], sizeof(*out));
    s->head = (s->head + 1) % RF_FAULT_ENTRIES;
    s->queued--;
    return true;
}
unsigned rf_faults_count(const rf_faults *s) { return s ? s->count : 0; }
bool rf_faults_view(const rf_faults *s, unsigned offset, rf_fault_view *out)
{
    if (!s || !out || offset >= s->count) return false;
    *out = s->entries[offset].view;
    return true;
}
void rf_faults_unprepare(rf_faults *s)
{
    if (!s) return;
    s->prepared = false;
    wipe(s->scratch, sizeof(s->scratch));
    wipe(s->retained, sizeof(s->retained));
}
void rf_faults_disable(rf_faults *s)
{
    if (!s) return;
    s->prepared = false;
    wipe(s->scratch, sizeof(s->scratch));
    wipe(s->retained, sizeof(s->retained));
    for (unsigned i = 0; i < s->count; i++) {
        rf_fault_view *view = &s->entries[i].view;
        if (view->state == RF_FAULT_PLANNED || view->state == RF_FAULT_READY)
            view->state = RF_FAULT_DISABLED;
    }
}
void rf_faults_finish(rf_faults *s)
{
    if (!s) return;
    for (unsigned i = 0; i < s->count; i++)
        if (s->entries[i].view.state == RF_FAULT_PLANNED || s->entries[i].view.state == RF_FAULT_READY)
            s->entries[i].view.state = RF_FAULT_MISSED;
    s->prepared = false;
    wipe(s->scratch, sizeof(s->scratch));
    wipe(s->retained, sizeof(s->retained));
}
void rf_faults_memory(const rf_faults *s, node_memory_inventory *out)
{
    if (s) node_memory_add(out, "lab_fault_owner", s, sizeof(*s));
}
