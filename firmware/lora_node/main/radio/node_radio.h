#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum { RADIO_BOARD_UNKNOWN, RADIO_HELTEC_V42_GC1109, RADIO_HELTEC_V43_KCT8103L } node_radio_variant;
typedef enum { RADIO_RESET, RADIO_FEM_POWER, RADIO_FEM_ENABLE, RADIO_FEM_MODE, RADIO_BUSY, RADIO_DIO1 } node_radio_signal;
typedef struct {
    void *context;
    int64_t (*now_us)(void *);
    void (*delay_us)(void *, uint32_t);
    bool (*set)(void *, node_radio_signal, bool);
    int (*get)(void *, node_radio_signal); // Negative means GPIO failure.
    bool (*transfer)(void *, const uint8_t *, uint8_t *, size_t);
} node_radio_bus;

typedef struct {
    node_radio_bus bus;
    node_radio_variant variant;
    bool available;
    const char *error;
} node_radio;

bool node_radio_init(node_radio *, const node_radio_bus *, node_radio_variant);
bool node_radio_stop(node_radio *);
const char *node_radio_variant_name(node_radio_variant);
