#pragma once
#include "radio/node_radio.h"
#include "radio/rf_fragments.h"
#include "radio/rf_frames.h"
#include "security/session_crypto.h"

typedef struct rf_echo rf_echo;
typedef struct
{
    rf_packet_port memory;
    int64_t (*now_us)(void *);
    node_radio *radio;
    rf_secure_session *security;
} rf_echo_port;
typedef struct
{
    bool requester, valid, done, failed, request_seen;
    uint32_t request_sequence, reply_sequence, attempts;
    int64_t tx_command_us, accepted_us;
    const char *reason;
} rf_echo_status;
typedef struct
{
    uint64_t session;
    uint32_t sequence, message, reference;
    uint16_t bytes;
    uint8_t source, destination, type;
} rf_echo_header;
typedef struct
{
    bool observed, decoded, accepted, result_ready;
    node_radio_event radio;
    rf_echo_header header;
    const char *rejection;
} rf_echo_event;

// One immutable expected body and one pending request per owned run.
rf_echo *rf_echo_create(rf_echo_port, const rf_message_plan *, const uint8_t *, bool requester,
                        uint32_t drain_us);
bool rf_echo_arm(rf_echo *, int64_t deadline);
bool rf_echo_start(rf_echo *, int64_t deadline);
void rf_echo_poll(rf_echo *, rf_echo_event *);
void rf_echo_abort(rf_echo *, const char *reason);
void rf_echo_snapshot(const rf_echo *, rf_echo_status *);
void rf_echo_destroy(rf_echo *);
void rf_echo_memory(const rf_echo *, node_memory_inventory *);
