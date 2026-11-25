#pragma once
#include "memory/buffers.h"
#include "radio/rf_fragments.h"
#include "radio/rf_frames.h"

#define RF_FAULT_ENTRIES 32U
#define RF_FAULT_BATCH 8U
#define RF_FAULT_RETAINED 16U

typedef enum { RF_FAULT_XOR = 1, RF_FAULT_REPLAY = 2 } rf_fault_action;
typedef enum {
    RF_FAULT_PLANNED, RF_FAULT_READY, RF_FAULT_APPLIED, RF_FAULT_FIRED,
    RF_FAULT_DISABLED, RF_FAULT_MISSED
} rf_fault_state;
typedef struct {
    char id[37];
    uint32_t message;
    uint16_t fragment, offset;
    uint8_t attempt, action, mask;
} rf_fault_spec;
typedef struct {
    rf_fault_spec spec;
    uint8_t state;
    uint32_t sequence;
    uint16_t frame_bytes;
    uint8_t before[32], after[32];
    int64_t applied_us;
} rf_fault_view;
typedef struct rf_faults rf_faults;

// Caller owns laboratory/session/state admission; this module has no encryption API.
rf_faults *rf_faults_create(rf_packet_port, uint64_t session, uint8_t source);
void rf_faults_destroy(rf_faults *);
bool rf_faults_can_configure(const rf_faults *, const rf_fault_spec *, size_t count, bool replace);
bool rf_faults_configure(rf_faults *, const rf_fault_spec *, size_t count, bool replace);
bool rf_faults_validate(const rf_faults *, const rf_message_plan *, uint8_t maximum_attempts);
bool rf_faults_prepare(rf_faults *, const rf_message_plan *, uint8_t maximum_attempts);
// Borrows an immutable original; returned wire remains valid until the next call/clear.
const uint8_t *rf_faults_transform(rf_faults *, const uint8_t *, size_t, uint8_t attempt,
                                  int64_t now_us);
const uint8_t *rf_faults_replay(rf_faults *, const char *id, size_t *bytes);
bool rf_faults_fired(rf_faults *, const char *id, int64_t now_us);
bool rf_faults_pop(rf_faults *, rf_fault_view *);
unsigned rf_faults_count(const rf_faults *);
bool rf_faults_view(const rf_faults *, unsigned offset, rf_fault_view *);
void rf_faults_unprepare(rf_faults *);
void rf_faults_disable(rf_faults *);
void rf_faults_finish(rf_faults *);
void rf_faults_memory(const rf_faults *, node_memory_inventory *);
