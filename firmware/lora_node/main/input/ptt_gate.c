#include "ptt_gate.h"
#include "generated/ptt_profile.h"

void ptt_gate_arm(ptt_gate *gate, bool pressed, int64_t now_us)
{
    *gate = (ptt_gate){.raw = pressed, .changed_us = now_us};
}

bool ptt_gate_step(ptt_gate *gate, bool pressed, int64_t now_us)
{
    if (now_us < gate->changed_us) ptt_gate_arm(gate, pressed, now_us);
    if (pressed != gate->raw) {
        gate->raw = pressed;
        gate->changed_us = now_us;
    }
    if (now_us - gate->changed_us < PTT_DEBOUNCE_US) return false;
    if (!pressed) gate->released = true;
    else if (gate->released) {
        gate->released = false;
        return true;
    }
    return false;
}
