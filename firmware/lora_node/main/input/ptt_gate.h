#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool raw, released;
    int64_t changed_us;
} ptt_gate;

void ptt_gate_arm(ptt_gate *gate, bool pressed, int64_t now_us);
bool ptt_gate_step(ptt_gate *gate, bool pressed, int64_t now_us);
