#pragma once

#include "lora_display_model.h"

namespace LoraBenchDisplay {

using State = LoraDisplayModel::State;

// Initializes only OLED power/reset/I2C and a core-0 refresh task. No RF action.
bool begin(const char* nodeLabel);
void setRole(bool transmitter);
void setState(State state);
// Valid range: 0 <= current <= total, 1 <= total <= 100. Resets state/history.
bool setTest(uint16_t current, uint16_t total);
bool ready();
bool layoutOk();
const char* stateName(State state);
State state();
uint16_t currentTest();
uint16_t totalTests();

}  // namespace LoraBenchDisplay
