#pragma once
#include "radio/node_radio.h"
#include "cJSON.h"

typedef struct { uint32_t fragment_payload_bytes, guard_us; } node_link_settings;
bool radio_config_parse(const cJSON *, node_radio_settings *, node_link_settings *);
cJSON *radio_config_radio(const node_radio_settings *, bool ldro);
cJSON *radio_config_link(const node_link_settings *);
cJSON *radio_config_result(const node_radio_settings *, const node_link_settings *, uint32_t revision);
