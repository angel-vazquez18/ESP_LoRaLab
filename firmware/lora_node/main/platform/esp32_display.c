#include "esp32_display.h"
#include "sdkconfig.h"

#ifdef CONFIG_LORALAB_OLED
#include <stdatomic.h>
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "display/oled_panel.h"
#include "generated/oled_board.h"

static QueueHandle_t pending;
static atomic_uint observed = DISPLAY_STARTING;
static uint8_t bitmap[OLED_FRAME_BYTES];

static bool post(void *context, const node_view *view)
{
    (void)context;
    unsigned state = atomic_load(&observed);
    return pending && (state == DISPLAY_STARTING || state == DISPLAY_READY) &&
        xQueueOverwrite(pending, view) == pdPASS;
}

static unsigned status(void *context)
{
    (void)context;
    return atomic_load(&observed);
}

static bool write(void *context, const uint8_t *data, size_t bytes, unsigned timeout_ms)
{
    return i2c_master_transmit(context, data, bytes, (int)timeout_ms) == ESP_OK;
}

static void worker(void *argument)
{
    (void)argument;
    i2c_master_bus_handle_t bus = NULL;
    i2c_master_dev_handle_t device = NULL;
    gpio_config_t outputs = {
        .pin_bit_mask = (1ULL << OLED_RESET_GPIO) | (1ULL << OLED_POWER_GPIO),
        .mode = GPIO_MODE_OUTPUT, .intr_type = GPIO_INTR_DISABLE,
    };
    if (gpio_config(&outputs) != ESP_OK ||
        gpio_set_level(OLED_POWER_GPIO, OLED_POWER_ON_LEVEL) != ESP_OK ||
        gpio_set_level(OLED_RESET_GPIO, 1) != ESP_OK) goto setup_failed;
    vTaskDelay(pdMS_TO_TICKS(20));
    if (gpio_set_level(OLED_RESET_GPIO, 0) != ESP_OK) goto setup_failed;
    vTaskDelay(pdMS_TO_TICKS(10));
    if (gpio_set_level(OLED_RESET_GPIO, 1) != ESP_OK) goto setup_failed;
    vTaskDelay(pdMS_TO_TICKS(20));
    i2c_master_bus_config_t config = {
        .i2c_port = I2C_NUM_0, .sda_io_num = OLED_SDA_GPIO, .scl_io_num = OLED_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    if (i2c_new_master_bus(&config, &bus) != ESP_OK) goto setup_failed;
    i2c_device_config_t panel = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = OLED_I2C_ADDRESS,
        .scl_speed_hz = 400000, .scl_wait_us = 2000,
    };
    if (i2c_master_bus_add_device(bus, &panel, &device) != ESP_OK) goto setup_failed;
    oled_panel_port port = {device, write};
    if (!oled_panel_initialize(port)) goto io_failed;
    while (true) {
        node_view view;
        if (xQueueReceive(pending, &view, portMAX_DELAY) != pdPASS) continue;
        node_view_bitmap(&view, bitmap);
        if (!oled_panel_frame(port, bitmap)) goto io_failed;
        atomic_store(&observed, DISPLAY_READY); // I2C completion, not observed pixels.
        vTaskDelay(pdMS_TO_TICKS(250));
    }
setup_failed:
    atomic_store(&observed, DISPLAY_SETUP_FAILED);
    goto done;
io_failed:
    atomic_store(&observed, DISPLAY_IO_FAILED);
done:
    if (device) i2c_master_bus_rm_device(device);
    if (bus) i2c_del_master_bus(bus);
    // Keep Vext on; an OLED fault must not power-cycle other Ve peripherals.
    vTaskDelete(NULL);
}
#endif

node_display_port esp32_display_init(void)
{
#ifdef CONFIG_LORALAB_OLED
    pending = xQueueCreate(1, sizeof(node_view));
    if (!pending || xTaskCreate(worker, "node_oled", 4096, NULL, 1, NULL) != pdPASS)
        atomic_store(&observed, DISPLAY_ALLOCATION_FAILED);
    return (node_display_port){post, status};
#else
    return (node_display_port){0};
#endif
}
