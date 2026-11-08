#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_err.h"
#include "esp_log.h"
#include "driver/usb_serial_jtag.h"

#include "transport/usb_transport.h"

void usb_transport_run(node_control *node)
{
    usb_serial_jtag_driver_config_t config = {
        .tx_buffer_size = 4096,
        .rx_buffer_size = 4096,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
    esp_log_level_set("*", ESP_LOG_NONE); // Application traffic is NDJSON only.

    static char tx[NODE_RECORD_BYTES];
    size_t tx_length = 0, tx_offset = 0;
    bool previously_connected = true;
    while (true) {
        bool connected = usb_serial_jtag_is_connected();
        node_control_link(node, connected);
        if (!connected && previously_connected)
            tx_length = tx_offset = 0;
        previously_connected = connected;

        uint8_t chunk[128];
        int received = usb_serial_jtag_read_bytes(chunk, sizeof(chunk), pdMS_TO_TICKS(20));
        if (received > 0)
            node_control_feed(node, chunk, (size_t)received);
        node_control_tick(node);

        if (connected) {
            if (tx_offset == tx_length) {
                tx_length = node_control_output(node, tx, sizeof(tx));
                tx_offset = 0;
            }
            if (tx_offset < tx_length) {
                int sent = usb_serial_jtag_write_bytes(tx + tx_offset, tx_length - tx_offset, 0);
                if (sent > 0)
                    tx_offset += (size_t)sent;
            }
        }
        vTaskDelay(1); // Yield without blocking control on TX backpressure.
    }
}
