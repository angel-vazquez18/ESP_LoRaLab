#pragma once
#include "control/node_control.h"

// Call once per boot; metadata strings remain valid for the firmware lifetime.
void esp32_platform_init(node_platform *platform);
