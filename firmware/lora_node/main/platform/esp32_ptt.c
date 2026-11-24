#include "esp32_ptt.h"
#include "sdkconfig.h"

#ifdef CONFIG_LORALAB_PTT
#include "driver/gpio.h"
#include "esp_err.h"
#include "generated/ptt_profile.h"

static bool pressed(void *context)
{
    (void)context;
    return gpio_get_level(PTT_GPIO) == 0;
}
#endif

void esp32_ptt_init(node_platform *platform)
{
#ifdef CONFIG_LORALAB_PTT
    if (!platform->audio.capture) return;
    gpio_config_t input = {
        .pin_bit_mask = 1ULL << PTT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&input));
    platform->ptt_pressed = pressed;
#else
    (void)platform;
#endif
}
