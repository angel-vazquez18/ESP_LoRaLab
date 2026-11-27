#pragma once
#include "control/node_control.h"

// Installs the selected serial driver, then owns the read/tick/write loop. Does not return.
void serial_transport_run(node_control *node);
