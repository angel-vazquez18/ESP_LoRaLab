#pragma once
#include <Arduino.h>
#include <driver/i2s.h>
enum gpio_mode_t { GPIO_MODE_OUTPUT };
enum gpio_pull_mode_t {
  GPIO_PULLUP_ONLY, GPIO_PULLDOWN_ONLY, GPIO_PULLUP_PULLDOWN, GPIO_FLOATING
};
esp_err_t gpio_reset_pin(gpio_num_t);
esp_err_t gpio_set_pull_mode(gpio_num_t, gpio_pull_mode_t);
esp_err_t gpio_set_level(gpio_num_t, uint32_t);
esp_err_t gpio_set_direction(gpio_num_t, gpio_mode_t);
esp_err_t gpio_input_enable(gpio_num_t);
int gpio_get_level(gpio_num_t);
