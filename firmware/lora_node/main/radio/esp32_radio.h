#pragma once
#include "radio/node_radio.h"
// Unselected builds leave all RF pins untouched and return unavailable status.
node_radio *esp32_radio_init(void);
