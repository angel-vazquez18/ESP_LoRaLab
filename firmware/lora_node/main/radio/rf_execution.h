#pragma once
#include "artifacts/artifact_store.h"
#include "radio/radio_config_json.h"
#include "radio/rf_ack.h"
#include "radio/rf_fragments.h"
#include "radio/rf_frames.h"
#include "radio/rf_echo.h"
#include "radio/rf_fault_json.h"
#include "radio/rf_reassembly.h"
#include "radio/rf_sender.h"
#include "security/session_crypto.h"
#include "source/worker.h"

typedef struct
{
    void *context;
    int64_t (*now_us)(void *);
    rf_hash hash;
    void (*random)(void *, void *, size_t);
    bool (*emit)(void *, const char *, cJSON *, const char *);
    bool (*room)(void *, unsigned);
    uint64_t (*drops)(void *);
    void *(*allocate)(void *, size_t);
    void (*release)(void *, void *);
    void (*before_release)(void *);
    encoded_worker_port source_worker;
    bool lab_faults;
} rf_execution_port;
typedef enum
{
    RF_IDLE,
    RF_PREPARING,
    RF_PREPARED,
    RF_ARMED,
    RF_RUNNING,
    RF_DRAINING,
    RF_REPORTING
} rf_phase;
typedef enum
{
    RF_OPEN,
    RF_CLOSE,
    RF_PREPARE,
    RF_ARM,
    RF_START,
    RF_STOP,
    RF_SUMMARY,
    RF_SOURCE, RF_FAULT_SET, RF_FAULT_FIRE, RF_FAULT_STATUS
} rf_action;
typedef struct
{
    rf_action action;
    char run[37], owner[37], operation[37], peer_device[17], peer_boot[32], session_text[17];
    uint64_t session;
    uint32_t revision, seed, bytes, duration_ms;
    uint32_t ack_timeout, reassembly, drain, processing, fault_us;
    node_link_settings link;
    bool protected_mode, encoded, fixed_source, echo;
    char source_artifact_id[37], expected_sha256[65];
    uint32_t sample_count;
    const cJSON *provision_keys, *fault_arguments;
    uint8_t role, source;
    const char *reason;
} rf_plan;
typedef struct
{
    rf_execution_port port;
    node_radio *radio;
    artifact_store *artifacts;
    rf_plan plan;
    rf_phase phase;
    bool used, sender, oom, finished, failed, started;
    bool radio_cleanup_failed, key_cleanup_failed, source_cleanup_failed;
    encoded_queue *queue;
    void *source_worker;
    uint32_t active_message, received_message, delivered_bitmap;
    uint32_t source_finished_messages, received_messages;
    char archive_sha[65];
    uint64_t drops_start;
    char artifact_id[37], sha_hex[65];
    const uint8_t *payload;
    uint8_t *generated, *recovered_output, expected_hash[32];
    bool source_borrowed, artifact_reserved;
    rf_reassembly *receiver;
    rf_secure_session *security;
    rf_sender *transmitter;
    rf_ack_receiver *acknowledgments;
    rf_faults *faults;
    rf_fault_view fault_pending, replay_view;
    bool fault_pending_valid, injected_tx;
    char replay_id[37];
    rf_echo *echo;
    rf_echo_status echo_status;
    char echo_reply_hex[431];
    bool ack_pending, ack_transmitting;
    uint8_t protected_ack_header[40];
    int64_t protected_ack_due;
    int64_t receive_deadline, drain_deadline;
    uint32_t frame_attempts, frame_originals;
    rf_message_plan fragments;
    uint16_t tx_fragment;
    uint32_t originals;
    uint32_t missing_count, missing_parts, missing_part;
    uint16_t missing_cursor;
    bool failure_result_reported, missing_evidence_incomplete;
    int64_t next_tx, first_fragment;
    uint32_t observations, accepted, duplicates, attempts, delivered;
    int64_t arm_deadline, deadline, first_tx, last_tx, first_rx, last_rx;
    const char *stop_reason;
} rf_execution;

void rf_execution_init(rf_execution *, node_radio *, artifact_store *, rf_execution_port);
bool rf_execution_command(const char *);
const char *rf_execution_check(rf_execution *, const char *name, const cJSON *, const char *run,
                               const char *owner, const char *role, const char *device,
                               uint32_t revision, const node_link_settings *, const char *operation,
                               rf_plan *, cJSON **result);
bool rf_execution_apply(rf_execution *, const rf_plan *);
void rf_execution_tick(rf_execution *);
bool rf_execution_abort(rf_execution *, const char *reason, bool close);
bool rf_execution_busy(const rf_execution *);
const char *rf_execution_state(const rf_execution *);

bool rf_execution_security_ready(const rf_execution *);

void rf_execution_memory(const rf_execution *, node_memory_inventory *);
