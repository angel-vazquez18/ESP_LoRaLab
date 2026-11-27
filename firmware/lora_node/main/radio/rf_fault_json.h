#pragma once
#include "cJSON.h"
#include "radio/rf_faults.h"

bool rf_fault_json_parse(const cJSON *, rf_fault_spec out[RF_FAULT_BATCH], size_t *count,
                         bool *replace);
cJSON *rf_fault_json_entry(const rf_fault_view *);
