#include "node_view.h"

const char *node_view_state_name(node_view_state state)
{
    static const char *const names[] = {
        "UNCLAIMED", "CLAIMED", "WAIT PTT", "CAPTURE", "PLAY",
        "ENCODE", "DECODE", "DIAGNOSTIC", "PREPARING", "PREPARED",
        "ARMED", "TX", "RX", "DRAINING", "STOPPING"
    };
    return (unsigned)state < sizeof(names) / sizeof(names[0]) ? names[state] : "UNKNOWN";
}

const char *node_display_status_name(unsigned status)
{
    static const char *const names[] = {
        "starting", "ready", "setup_failed", "io_failed", "allocation_failed"
    };
    return status < sizeof(names) / sizeof(names[0]) ? names[status] : "unobserved";
}

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

void node_view_text(const node_view *view, char lines[NODE_VIEW_ROWS][NODE_VIEW_COLUMNS + 1])
{
    memset(lines, 0, NODE_VIEW_ROWS * (NODE_VIEW_COLUMNS + 1));
    if (!view) return;
    char role = view->role == 'A' || view->role == 'B' ? view->role : '-';
    snprintf(lines[0], NODE_VIEW_COLUMNS + 1, "LORALAB NODE %c", role);
    snprintf(lines[1], NODE_VIEW_COLUMNS + 1, "%s", node_view_state_name(view->state));
    if (view->total)
        snprintf(lines[2], NODE_VIEW_COLUMNS + 1, "WORK %" PRIu32 "/%" PRIu32, view->completed, view->total);
    else snprintf(lines[2], NODE_VIEW_COLUMNS + 1, "NO FINITE WORK COUNT");
    snprintf(lines[3], NODE_VIEW_COLUMNS + 1, "LINK TX %" PRIu32 " RX %" PRIu32, view->tx_attempts, view->delivered);
    snprintf(lines[4], NODE_VIEW_COLUMNS + 1, "%s", view->error_code[0] ? "RECORDED ERROR" : "NO RECORDED ERROR");
    snprintf(lines[5], NODE_VIEW_COLUMNS + 1, "%.25s", view->error_code);
    snprintf(lines[6], NODE_VIEW_COLUMNS + 1, "USB %s %s", view->linked ? "UP" : "LOST", view->claimed ? "OWNED" : "UNOWNED");
    snprintf(lines[7], NODE_VIEW_COLUMNS + 1, "UP %" PRIu64 " S", view->uptime_us / 1000000);
}

// Project-drawn four-column, six-row uppercase glyphs; one blank column separates them.
static const uint8_t glyphs[36][6] = {
    {6,9,15,9,9,9}, {14,9,14,9,9,14}, {7,8,8,8,8,7}, {14,9,9,9,9,14},
    {15,8,14,8,8,15}, {15,8,14,8,8,8}, {7,8,11,9,9,7}, {9,9,15,9,9,9},
    {7,2,2,2,2,7}, {1,1,1,1,9,6}, {9,10,12,10,9,9}, {8,8,8,8,8,15},
    {9,15,15,9,9,9}, {9,13,13,11,11,9}, {6,9,9,9,9,6}, {14,9,14,8,8,8},
    {6,9,9,9,11,7}, {14,9,14,10,9,9}, {7,8,6,1,1,14}, {15,2,2,2,2,2},
    {9,9,9,9,9,6}, {9,9,9,9,6,6}, {9,9,9,15,15,9}, {9,9,6,6,9,9},
    {9,9,6,2,2,2}, {15,1,2,4,8,15},
    {6,9,9,9,9,6}, {2,6,2,2,2,7}, {6,9,1,2,4,15}, {14,1,6,1,9,6},
    {2,6,10,15,2,2}, {15,8,14,1,9,6}, {7,8,14,9,9,6}, {15,1,2,4,4,4},
    {6,9,6,9,9,6}, {6,9,9,7,1,14},
};

static uint8_t glyph_row(char character, unsigned row)
{
    if (character >= 'A' && character <= 'Z') return glyphs[character - 'A'][row];
    if (character >= '0' && character <= '9') return glyphs[26 + character - '0'][row];
    if (character == ' ') return 0;
    if (character == '-') return row == 2 ? 15 : 0;
    if (character == '_') return row == 5 ? 15 : 0;
    if (character == ':') return row == 1 || row == 4 ? 6 : 0;
    if (character == '.') return row == 5 ? 4 : 0;
    if (character == '/') return (const uint8_t[]){1,1,2,4,8,8}[row];
    return (const uint8_t[]){6,9,1,2,0,2}[row];
}

void node_view_bitmap(const node_view *view, uint8_t bitmap[1024])
{
    if (!bitmap) return;
    memset(bitmap, 0, 1024);
    char lines[NODE_VIEW_ROWS][NODE_VIEW_COLUMNS + 1];
    node_view_text(view, lines);
    for (unsigned line = 0; line < NODE_VIEW_ROWS; line++)
        for (unsigned column = 0; column < NODE_VIEW_COLUMNS && lines[line][column]; column++)
            for (unsigned row = 0; row < 6; row++) {
                uint8_t pixels = glyph_row(lines[line][column], row);
                for (unsigned bit = 0; bit < 4; bit++)
                    if (pixels & (8U >> bit))
                        bitmap[line * 128 + column * 5 + bit] |= 1U << (row + 1);
            }
}
