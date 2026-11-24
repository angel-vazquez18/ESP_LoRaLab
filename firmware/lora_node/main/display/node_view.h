#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef enum {
    VIEW_UNCLAIMED, VIEW_CLAIMED, VIEW_WAIT_PTT, VIEW_CAPTURE, VIEW_PLAY,
    VIEW_ENCODE, VIEW_DECODE, VIEW_DIAGNOSTIC, VIEW_PREPARING, VIEW_PREPARED,
    VIEW_ARMED, VIEW_TX, VIEW_RX, VIEW_DRAINING, VIEW_STOPPING
} node_view_state;

typedef struct {
    node_view_state state;
    char role;
    bool claimed, linked;
    uint32_t completed, total, tx_attempts, delivered;
    uint64_t uptime_us;
    char error_code[40]; // Symbolic last error, never a command argument/message.
} node_view;

typedef enum {
    DISPLAY_STARTING, DISPLAY_READY, DISPLAY_SETUP_FAILED, DISPLAY_IO_FAILED,
    DISPLAY_ALLOCATION_FAILED
} node_display_status;

typedef struct {
    bool (*post)(void *, const node_view *); // Must return without waiting for I/O.
    unsigned (*status)(void *); // Nonblocking observed worker status.
} node_display_port;

const char *node_view_state_name(node_view_state state);
const char *node_display_status_name(unsigned status);

#define NODE_VIEW_ROWS 8U
#define NODE_VIEW_COLUMNS 25U
void node_view_text(const node_view *view, char lines[NODE_VIEW_ROWS][NODE_VIEW_COLUMNS + 1]);
void node_view_bitmap(const node_view *view, uint8_t bitmap[1024]);
