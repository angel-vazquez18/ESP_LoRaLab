#pragma once
#include "artifacts/artifact_store.h"
#include "radio/radio_config_json.h"
#include "radio/rf_frames.h"

typedef struct
{
    void *context;
    int64_t (*now_us)(void *);
    rf_hash hash;
    void (*random)(void *, void *, size_t);
    bool (*emit)(void *, const char *, cJSON *, const char *);
    bool (*room)(void *, unsigned);
    uint64_t (*drops)(void *);
} rf_execution_port;
typedef enum
{
    RF_IDLE,
    RF_PREPARING,
    RF_PREPARED,
    RF_ARMED,
    RF_RUNNING
} rf_phase;
typedef enum
{
    RF_OPEN,
    RF_CLOSE,
    RF_PREPARE,
    RF_ARM,
    RF_START,
    RF_STOP,
    RF_SUMMARY
} rf_action;
typedef struct
{
    rf_action action;
    char run[37], owner[37], operation[37], peer_device[17], peer_boot[32], session_text[17];
    uint64_t session;
    uint32_t revision, seed, bytes, duration_ms;
    uint32_t ack_timeout, reassembly, drain, processing;
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
    uint64_t drops_start;
    char artifact_id[37], sha_hex[65];
    uint8_t payload[215];
    rf_single_receiver receiver;
    uint32_t observations, accepted, duplicates, attempts, delivered;
    int64_t deadline, first_tx, last_tx, first_rx, last_rx;
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
