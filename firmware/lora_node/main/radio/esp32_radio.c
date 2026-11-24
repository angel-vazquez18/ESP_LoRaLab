#include "radio/esp32_radio.h"
#include "generated/radio_board.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include <string.h>

#if defined(CONFIG_LORALAB_RADIO_HELTEC_V43) && defined(CONFIG_LORALAB_AUDIO_CAPTURE)
#error "V4.3 RF uses GPIO5; the existing microphone WS GPIO5 profile conflicts"
#endif

typedef struct {
    spi_device_handle_t spi;
    int mode_pin;
    bool pending;
    spi_transaction_t transaction;
    uint8_t tx[260], rx[260];
} esp32_radio_bus;
static esp32_radio_bus hardware;
static node_radio radio;
static int pin(esp32_radio_bus *h, node_radio_signal signal)
{
    const int pins[] = {RADIO_GPIO_RESET, RADIO_GPIO_FEM_POWER, RADIO_GPIO_FEM_ENABLE, h->mode_pin, RADIO_GPIO_BUSY, RADIO_GPIO_DIO1};
    return pins[signal];
}
static int64_t now(void *context) { (void)context; return esp_timer_get_time(); }
static void delay(void *context, uint32_t us)
{
    (void)context;
    // Yield on millisecond waits; short reset pulses need microsecond timing.
    if (us >= 1000) vTaskDelay(pdMS_TO_TICKS(us / 1000) + 1);
    else esp_rom_delay_us(us);
}
static bool set(void *context, node_radio_signal signal, bool value)
{ return gpio_set_level(pin(context, signal), value) == ESP_OK; }
static int get(void *context, node_radio_signal signal)
{ return gpio_get_level(pin(context, signal)); }
static bool transfer(void *context, const uint8_t *tx, uint8_t *rx, size_t length)
{
    esp32_radio_bus *h = context;
    if (h->pending || length > sizeof(h->tx)) return false;
    memcpy(h->tx, tx, length);
    h->transaction = (spi_transaction_t){.length = length * 8, .tx_buffer = h->tx, .rx_buffer = h->rx};
    if (spi_device_queue_trans(h->spi, &h->transaction, pdMS_TO_TICKS(20) + 1) != ESP_OK) return false;
    h->pending = true;
    spi_transaction_t *completed = NULL;
    if (spi_device_get_trans_result(h->spi, &completed, pdMS_TO_TICKS(20) + 1) != ESP_OK) return false;
    h->pending = false;
    if (completed != &h->transaction) return false;
    memcpy(rx, h->rx, length);
    return true;
}
node_radio *esp32_radio_init(void)
{
    radio = (node_radio){.error = "radio_board_unselected"};
    node_radio_variant variant = RADIO_BOARD_UNKNOWN;
#if defined(CONFIG_LORALAB_RADIO_HELTEC_V42)
    variant = RADIO_HELTEC_V42_GC1109;
    hardware.mode_pin = RADIO_GPIO_V42_MODE;
#elif defined(CONFIG_LORALAB_RADIO_HELTEC_V43)
    variant = RADIO_HELTEC_V43_KCT8103L;
    hardware.mode_pin = RADIO_GPIO_V43_MODE;
#endif
    if (variant == RADIO_BOARD_UNKNOWN) return &radio;
    radio.variant = variant;
    uint64_t outputs = (1ULL << RADIO_GPIO_RESET) | (1ULL << RADIO_GPIO_FEM_POWER) | (1ULL << RADIO_GPIO_FEM_ENABLE) | (1ULL << hardware.mode_pin);
    gpio_config_t output = {.pin_bit_mask = outputs, .mode = GPIO_MODE_OUTPUT};
    gpio_config_t input = {.pin_bit_mask = (1ULL << RADIO_GPIO_BUSY) | (1ULL << RADIO_GPIO_DIO1), .mode = GPIO_MODE_INPUT};
    radio.error = "radio_bus_setup_failed";
    if (gpio_config(&output) != ESP_OK || gpio_config(&input) != ESP_OK) return &radio;
    gpio_set_level(RADIO_GPIO_FEM_POWER, 0);
    gpio_set_level(RADIO_GPIO_FEM_ENABLE, 0);
    gpio_set_level(hardware.mode_pin, 0);
    gpio_set_level(RADIO_GPIO_RESET, 0);
    spi_bus_config_t bus = {.mosi_io_num = RADIO_GPIO_MOSI, .miso_io_num = RADIO_GPIO_MISO, .sclk_io_num = RADIO_GPIO_SCK,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 260};
    if (spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_DISABLED) != ESP_OK) return &radio;
    spi_device_interface_config_t device = {.clock_speed_hz = 4000000, .mode = 0,
        .spics_io_num = RADIO_GPIO_NSS, .queue_size = 1};
    if (spi_bus_add_device(SPI2_HOST, &device, &hardware.spi) != ESP_OK) {
        spi_bus_free(SPI2_HOST);
        return &radio;
    }
    node_radio_bus port = {&hardware, now, delay, set, get, transfer};
    node_radio_init(&radio, &port, variant);
    return &radio;
}
