#pragma once

#include <Arduino.h>

namespace Pins {

#if defined(AUDIO_BOARD_HELTEC_V4) && AUDIO_BOARD_HELTEC_V4

// Heltec WiFi LoRa 32 V4.3 ESP32-S3R2, Rev B external wiring.
// GPS/GNSS must remain disconnected; GPIO38-41 are reused below.
// GPIO15-18 get no external wiring; OLED still uses GPIO17/18 internally.
constexpr gpio_num_t MIC_BCLK = GPIO_NUM_4;
constexpr gpio_num_t MIC_WS = GPIO_NUM_6;
constexpr gpio_num_t MIC_SD = GPIO_NUM_38;
constexpr gpio_num_t SPK_BCLK = GPIO_NUM_40;
constexpr gpio_num_t SPK_WS = GPIO_NUM_41;
constexpr gpio_num_t SPK_DOUT = GPIO_NUM_47;
// Add 1 kOhm from SD/MODE to GND. USB 5V supplies amplifier VIN.
constexpr gpio_num_t SPK_SD = GPIO_NUM_48;
constexpr gpio_num_t PTT_BUTTON = GPIO_NUM_39;  // Reserved; PTT disabled for now.

#else

// -----------------------------------------------------------------------------
// INMP441 microphone.
// -----------------------------------------------------------------------------

constexpr gpio_num_t MIC_BCLK = GPIO_NUM_26;
constexpr gpio_num_t MIC_WS = GPIO_NUM_25;
constexpr gpio_num_t MIC_SD = GPIO_NUM_33;

// -----------------------------------------------------------------------------
// MAX98357A amplifier.
// -----------------------------------------------------------------------------

constexpr gpio_num_t SPK_BCLK = GPIO_NUM_14;
constexpr gpio_num_t SPK_WS = GPIO_NUM_16;
constexpr gpio_num_t SPK_DOUT = GPIO_NUM_17;
// MAX98357A SD/MODE: move row 28 OFF the 3V3 rail and onto GPIO27.
// Add 1 kOhm from SD to GND; verify SD < 0.08 V while MCU reset is held.
constexpr gpio_num_t SPK_SD = GPIO_NUM_27;

// -----------------------------------------------------------------------------
// Push-to-talk button.
// Button is wired between GPIO 4 and GND.
// -----------------------------------------------------------------------------

constexpr gpio_num_t PTT_BUTTON = GPIO_NUM_4;

#endif

static_assert(SPK_SD != SPK_BCLK && SPK_SD != SPK_WS && SPK_SD != SPK_DOUT &&
              SPK_SD != MIC_BCLK && SPK_SD != MIC_WS && SPK_SD != MIC_SD,
              "Amplifier shutdown must have its own GPIO");

}  // namespace Pins
