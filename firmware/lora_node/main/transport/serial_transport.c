#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_err.h"
#include "esp_log.h"
#include "sdkconfig.h"

#ifdef CONFIG_LORALAB_CONTROL_UART0
#include "driver/uart.h"
#else
#include "driver/usb_serial_jtag.h"
#endif

#include "transport/serial_transport.h"

static void install(void)
{
#ifdef CONFIG_LORALAB_CONTROL_UART0
    const uart_config_t config = {
        .baud_rate = 115200,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &config));
    ESP_ERROR_CHECK(uart_set_pin(UART_NUM_0, 43, 44, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 4096, 0, 0, NULL, 0));
#else
    usb_serial_jtag_driver_config_t config = {
        .tx_buffer_size = 4096,
        .rx_buffer_size = 4096,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
#endif
}

static bool link_active(void)
{
#ifdef CONFIG_LORALAB_CONTROL_UART0
    return true; // A bare UART has no cable-detection signal. The lease bounds ownership.
#else
    return usb_serial_jtag_is_connected();
#endif
}

static int read_chunk(uint8_t *buffer, size_t length)
{
#ifdef CONFIG_LORALAB_CONTROL_UART0
    return uart_read_bytes(UART_NUM_0, buffer, length, pdMS_TO_TICKS(20));
#else
    return usb_serial_jtag_read_bytes(buffer, length, pdMS_TO_TICKS(20));
#endif
}

static int write_chunk(const char *buffer, size_t length)
{
#ifdef CONFIG_LORALAB_CONTROL_UART0
    return uart_tx_chars(UART_NUM_0, buffer, length);
#else
    return usb_serial_jtag_write_bytes(buffer, length, 0);
#endif
}

void serial_transport_run(node_control *node)
{
    install();
    esp_log_level_set("*", ESP_LOG_NONE); // Application traffic is NDJSON only.

    static char tx[NODE_RECORD_BYTES];
    size_t tx_length = 0, tx_offset = 0;
    bool previously_connected = true;
    while (true) {
        bool connected = link_active();
        node_control_link(node, connected);
        if (!connected && previously_connected)
            tx_length = tx_offset = 0;
        previously_connected = connected;

        uint8_t chunk[128];
        int received = read_chunk(chunk, sizeof(chunk));
        if (received > 0)
            node_control_feed(node, chunk, (size_t)received);
        node_control_tick(node);

        if (connected) {
            if (tx_offset == tx_length) {
                tx_length = node_control_output(node, tx, sizeof(tx));
                tx_offset = 0;
            }
            if (tx_offset < tx_length) {
                int sent = write_chunk(tx + tx_offset, tx_length - tx_offset);
                if (sent > 0)
                    tx_offset += (size_t)sent;
            }
        }
        vTaskDelay(1); // Yield without blocking control on TX backpressure.
    }
}
