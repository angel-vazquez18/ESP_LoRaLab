#pragma once
#include "control/node_control.h"

// Installs USB, then owns the read/tick/write loop. Does not return.
void usb_transport_run(node_control *node);
