#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <vector>
#include <Arduino.h>
#include <driver/i2s.h>
#include <driver/gpio.h>
#include <hal/i2s_ll.h>
#include "audio_manager.h"
#include "config.h"
#include "pins.h"

FakeSerial Serial;
static std::vector<int16_t> output;
static i2s_config_t configs[2];
static int failedPort = -1;
static int failedPinPort = -1;
static unsigned uninstallCount = 0, readSample = 0, queuedBlocks = 0;
static int writeMode = 0;  // 1 partial, 2 zero progress, 3 error, 4 byte, 5 half-frame
static bool stalledRead = false;
static uint8_t pcm[Config::AUDIO_BUFFER_BYTES];

// Model the driver's auto-start-on-install and enforce the amp's external
// startup contract. This cannot simulate the silicon's first clock edges.
FakeI2sHw fakeI2sHardware[2] = {{0}, {1}};
enum class InitFault {
  None, Stop, Clear, Monitor, BclkHigh, WsHigh, Enable, Start,
  GpioBclkHigh, GpioWsHigh, Pull
};
static InitFault initFault = InitFault::None;
// ESP32-S3's valid GPIO range includes GPIO48.
static int levels[49];
static bool gpioOutputs[49];
static gpio_pull_mode_t gpioPulls[49];
static bool installed = false, running = false, routed = false;
static bool resetDone = false, silenceReady = false, leftFirst = false, continuous = false;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
static bool txConfigurationLatched = false;
#endif
static unsigned starts = 0, stops = 0, enables = 0, installs = 0;
static uint64_t timeUs = 0, enabledAt = 0, disabledAt = 0, startedAt = 0;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
constexpr size_t WIRE_SAMPLE_BYTES = sizeof(int32_t);
#else
constexpr size_t WIRE_SAMPLE_BYTES = sizeof(int16_t);
#endif
constexpr size_t WIRE_FRAME_BYTES = WIRE_SAMPLE_BYTES * 2;
static void freshHardware() {
  initFault = InitFault::None;
  memset(levels, 0, sizeof(levels));
  memset(gpioOutputs, 0, sizeof(gpioOutputs));
  for (auto& pull : gpioPulls) pull = GPIO_FLOATING;
  installed = running = routed = resetDone = silenceReady = leftFirst = continuous = false;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  txConfigurationLatched = false;
#endif
  starts = stops = enables = installs = uninstallCount = 0;
  timeUs = enabledAt = disabledAt = startedAt = 0;
  failedPort = failedPinPort = -1;
  output.clear();
}
void delay(uint32_t ms) { timeUs += ms * 1000ULL; }
void delayMicroseconds(uint32_t us) { timeUs += us; }
esp_err_t gpio_reset_pin(gpio_num_t p) {
  assert(levels[Pins::SPK_SD] == 0);
  gpioOutputs[p] = false;
  gpioPulls[p] = GPIO_PULLUP_ONLY;  // Matches gpio_reset_pin in ESP-IDF.
  if (p == Pins::SPK_BCLK || p == Pins::SPK_WS) routed = false;
  return ESP_OK;
}
esp_err_t gpio_set_pull_mode(gpio_num_t p, gpio_pull_mode_t mode) {
  assert(!gpioOutputs[p] && mode == GPIO_PULLDOWN_ONLY);
  if (p == Pins::SPK_WS && initFault == InitFault::Pull) return -1;
  gpioPulls[p] = mode;
  return ESP_OK;
}
esp_err_t gpio_set_level(gpio_num_t p, uint32_t value) {
  if (p == Pins::SPK_SD) {
    if (value) {
      assert(installed && routed && resetDone && silenceReady);
#if defined(CONFIG_IDF_TARGET_ESP32S3)
      assert(running && starts == 1 && timeUs - startedAt >= Config::AMP_STARTUP_SETTLE_MS * 1000ULL);
#else
      assert(!running);
#endif
      assert(timeUs - disabledAt >= 1000);
      if (initFault == InitFault::Enable) return -1;
      enabledAt = timeUs;
      ++enables;
    } else { disabledAt = timeUs; }
  }
  levels[p] = value;
  return ESP_OK;
}
esp_err_t gpio_set_direction(gpio_num_t p, gpio_mode_t mode) {
  assert(mode == GPIO_MODE_OUTPUT && levels[p] == 0);
  gpioOutputs[p] = true;
  return ESP_OK;
}
esp_err_t gpio_input_enable(gpio_num_t) {
  return routed && initFault == InitFault::Monitor ? -1 : ESP_OK;
}
int gpio_get_level(gpio_num_t p) {
  assert(!running);
  if (routed) {
    if ((p == Pins::SPK_BCLK && initFault == InitFault::BclkHigh) ||
        (p == Pins::SPK_WS && initFault == InitFault::WsHigh)) return 1;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
    // Real ESP32-S3 hardware idles WS high even after reset/update and with
    // a pull-down. The 512 kHz mode must start successfully in this state.
    if (p == Pins::SPK_WS) {
      assert(gpioPulls[p] == GPIO_PULLDOWN_ONLY);
      return 1;
    }
#endif
  } else {
    assert(!installed && gpioOutputs[p]);
    if ((p == Pins::SPK_BCLK && initFault == InitFault::GpioBclkHigh) ||
        (p == Pins::SPK_WS && initFault == InitFault::GpioWsHigh)) return 1;
  }
  return levels[p];
}
void i2s_ll_tx_reset(FakeI2sHw* hw) {
  assert(hw->port == 1 && installed && !running && !routed);
  resetDone = true;
}
#if defined(CONFIG_IDF_TARGET_ESP32S3)
void i2s_ll_tx_set_ws_idle_pol(FakeI2sHw* hw, bool high) {
  assert(hw->port == 1 && resetDone && !running);
  leftFirst = !high;
  txConfigurationLatched = false;
}
void i2s_ll_tx_update(FakeI2sHw* hw) {
  assert(hw->port == 1 && installed && resetDone && !running && !routed);
  txConfigurationLatched = true;
}
#else
void i2s_ll_tx_enable_right_first(FakeI2sHw* hw, bool right) {
  assert(hw->port == 1 && resetDone && !running);
  leftFirst = !right;
}
void i2s_ll_tx_stop_on_fifo_empty(FakeI2sHw* hw, bool stop) {
  assert(hw->port == 1 && !running);
  continuous = !stop;
}
#endif
const char* esp_err_to_name(esp_err_t) { return "FAKE_ERROR"; }
esp_err_t i2s_driver_install(i2s_port_t p, const i2s_config_t* c, int, void*) {
  ++installs;
  if (p == 1) {
    assert(!installed && !routed && levels[Pins::SPK_SD] == 0);
    for (auto pin : {Pins::SPK_BCLK, Pins::SPK_WS, Pins::SPK_DOUT})
      assert(gpioOutputs[pin] && levels[pin] == 0);
    if (p != failedPort) {
      installed = running = true;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
      // S3's legacy driver owns a circular GDMA ring; no FIFO-stop setting.
      continuous = true;
#endif
    }
  }
  configs[p] = *c; return p == failedPort ? -1 : ESP_OK;
}
esp_err_t i2s_driver_uninstall(i2s_port_t p) {
  if (p == 1) {
    assert(installed && levels[Pins::SPK_SD] == 0 && timeUs - disabledAt >= 1000);
    installed = running = false;
  }
  ++uninstallCount; return ESP_OK;
}
esp_err_t i2s_stop(i2s_port_t p) {
  assert(p == 1 && installed && !routed && levels[Pins::SPK_SD] == 0);
  ++stops;
  if (initFault == InitFault::Stop) return -1;
  running = false;
  return ESP_OK;
}
esp_err_t i2s_start(i2s_port_t p) {
  assert(p == 1 && installed && !running && routed && leftFirst && continuous && silenceReady);
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  assert(levels[Pins::SPK_SD] == 0 && enables == 0);
#else
  assert(levels[Pins::SPK_SD] == 1 && timeUs - enabledAt >= 10);
#endif
  ++starts;
  startedAt = timeUs;
  // Also test cleanup when a failed API has already started the hardware.
  running = true;
  return initFault == InitFault::Start ? -1 : ESP_OK;
}
esp_err_t i2s_set_pin(i2s_port_t p, const i2s_pin_config_t* pins) {
  if (p == 1) {
    assert(installed && !running && resetDone && silenceReady && levels[Pins::SPK_SD] == 0);
#if defined(CONFIG_IDF_TARGET_ESP32S3)
    assert(txConfigurationLatched);
#endif
    assert(pins->bck_io_num == Pins::SPK_BCLK && pins->ws_io_num == Pins::SPK_WS);
    assert(pins->data_out_num == Pins::SPK_DOUT);
    routed = true; // A failure can leave partially assigned pins.
  }
  assert(pins->mck_io_num == -1); return p == failedPinPort ? -1 : ESP_OK;
}
esp_err_t i2s_zero_dma_buffer(i2s_port_t p) {
  assert(p == I2S_NUM_1);  // RX must not be cleared in place.
  if (!running) {
    assert(resetDone && !routed);
    if (initFault == InitFault::Clear) return -1;
    silenceReady = true;
  }
  return ESP_OK;
}
esp_err_t i2s_write(i2s_port_t p, const void* data, size_t length, size_t* written, uint32_t timeout) {
  assert(p == I2S_NUM_1 && timeout == Config::I2S_TIMEOUT_MS);
  assert(running && levels[Pins::SPK_SD] == 1);
  assert(length <= Config::I2S_DMA_FRAMES * WIRE_FRAME_BYTES);
  *written = 0;
  if (writeMode == 2) return ESP_OK;
  if (writeMode == 3) return -1;
  if (writeMode == 4) { *written = 1; return ESP_OK; }
  if (writeMode == 5) { *written = WIRE_SAMPLE_BYTES; return ESP_OK; }
  *written = writeMode == 1 && length > WIRE_FRAME_BYTES ? WIRE_FRAME_BYTES : length;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  const auto* samples = static_cast<const int32_t*>(data);
  for (size_t i = 0; i < *written / sizeof(int32_t); ++i) {
    // Verify actual wire values, including negative/full-scale PCM and the
    // silent tail, before decoding to the shared logical sample assertions.
    assert((static_cast<uint32_t>(samples[i]) & 0xffffU) == 0);
    output.push_back(static_cast<int16_t>(samples[i] / 65536));
  }
#else
  const auto* samples = static_cast<const int16_t*>(data);
  output.insert(output.end(), samples, samples + *written / 2);
#endif
  return ESP_OK;
}
static int32_t rawSample(unsigned index) {
  const int16_t high[] = {0, 100, -100, 20000, -20000, 1, -1, 1234};
  return static_cast<int32_t>(high[index % 8]) * 65536;
}
esp_err_t i2s_read(i2s_port_t p, void* data, size_t length, size_t* read, uint32_t timeout) {
  assert(p == I2S_NUM_0);
  *read = 0;
  if (timeout == 0) {
    if (queuedBlocks) { --queuedBlocks; memset(data, 0x55, length); *read = length; }
    return ESP_OK;
  }
  assert(timeout == Config::I2S_TIMEOUT_MS);
  if (stalledRead) return ESP_OK;
  auto* words = static_cast<int32_t*>(data);
  for (size_t i = 0; i < length / 4; ++i) words[i] = rawSample(readSample++);
  *read = length;
  return ESP_OK;
}

int main() {
#if defined(AUDIO_BOARD_HELTEC_V4) && AUDIO_BOARD_HELTEC_V4
  static_assert(Pins::MIC_BCLK == 4 && Pins::MIC_WS == 6 && Pins::MIC_SD == 38,
                "Heltec microphone pins must match the Rev B wiring");
  static_assert(Pins::SPK_BCLK == 40 && Pins::SPK_WS == 41 &&
                Pins::SPK_DOUT == 47 && Pins::SPK_SD == 48,
                "Heltec amplifier pins must match the Rev B wiring");
  static_assert(Pins::PTT_BUTTON == 39 && !Config::ENABLE_PTT,
                "Heltec PTT stays disconnected and disabled during bring-up");
#endif
  freshHardware();
  AudioManager audio;
  assert(!audio.playTestTone());
  assert(audio.begin());
  assert(audio.microphoneReady() == Config::ENABLE_MIC);
  assert(audio.speakerReady() == Config::ENABLE_SPEAKER);
  assert(installs == unsigned(Config::ENABLE_MIC) + unsigned(Config::ENABLE_SPEAKER));
  const auto initializedAt = timeUs;
  assert(audio.begin() && timeUs == initializedAt); // No repeated shutdown/init.
  if (!Config::ENABLE_SPEAKER) {
    assert(levels[Pins::SPK_SD] == 0 && !running && !audio.playTestTone());
    assert(gpioOutputs[Pins::SPK_SD] && !installed && !routed);
    assert(starts == 0 && stops == 0 && enables == 0);
    if (Config::ENABLE_MIC) {
      assert(configs[0].bits_per_sample == 32 && configs[0].channel_format == I2S_CHANNEL_FMT_ONLY_LEFT);
      queuedBlocks = 7;
      assert(audio.recordThreeSeconds(pcm, sizeof(pcm)));
      assert(readSample == Config::MIC_DMA_WORDS + Config::AUDIO_SAMPLES);
      const int16_t expected[] = {0, 200, -200, 32767, -32768, 2, -2, 2468};
      for (size_t i = 0; i < sizeof(expected) / sizeof(expected[0]); ++i) {
        int16_t value;
        memcpy(&value, pcm + i * sizeof(value), sizeof(value));
        assert(value == expected[i]);
      }
      assert(!audio.playPcm(pcm, sizeof(pcm)));
      assert(output.empty() && levels[Pins::SPK_SD] == 0 && !running);
      puts("PASS: mic-only records PCM with amplifier held off and no speaker I2S driver");
    } else {
      puts("PASS: serial-only holds SD low and installs no I2S drivers");
    }
    return 0;
  }
  assert(starts == 1 && stops == 1 && enables == 1);
  assert(timeUs - enabledAt >= Config::AMP_STARTUP_SETTLE_MS * 1000ULL);
  if (!Config::ENABLE_MIC) {
    assert(audio.playTestTone() && running && starts == 1 && stops == 1);
    puts("PASS: speaker-only sequenced startup, no microphone dependency");
    return 0;
  }
  assert(configs[0].bits_per_sample == 32 && configs[0].channel_format == I2S_CHANNEL_FMT_ONLY_LEFT);
  assert(configs[1].bits_per_sample == WIRE_SAMPLE_BYTES * 8 &&
         configs[1].channel_format == I2S_CHANNEL_FMT_RIGHT_LEFT);
  writeMode = 1;  // Force many valid short writes; no samples may be skipped.
  assert(audio.playTestTone(1000));
  const size_t tail = (Config::I2S_DMA_BUFFERS + 1) * Config::I2S_DMA_FRAMES;
  assert(output.size() == (8064 + tail) * 2);
  assert((output.size() / 2) % Config::I2S_DMA_FRAMES == 0);
  for (size_t i = 0; i < output.size() / 2; ++i) {
    const int16_t expected = i >= 8000 ? 0 : (i % 8 < 4 ? 2000 : -2000);
    assert(output[i * 2] == expected && output[i * 2 + 1] == expected);
  }
  // A short tone, an exact descriptor, and repeated one-second tones all
  // retain their sample count and leave the driver at a descriptor boundary.
  writeMode = 0;
  for (uint32_t durationMs : {1U, 16U, 1000U, 1000U, 15000U}) {
    output.clear();
    assert(audio.playTestTone(durationMs));
    const size_t toneFrames = 8 * durationMs;
    assert((output.size() / 2) % Config::I2S_DMA_FRAMES == 0);
    assert(output.size() / 2 >= toneFrames + tail);
    assert(output.size() / 2 < toneFrames + tail + Config::I2S_DMA_FRAMES);
    for (size_t i = 0; i < output.size() / 2; ++i) {
      const int16_t expected = i >= toneFrames ? 0 : (i % 8 < 4 ? 2000 : -2000);
      assert(output[2 * i] == expected && output[2 * i + 1] == expected);
    }
  }
  for (int mode = 2; mode <= 5; ++mode) {
    writeMode = mode;
    assert(!audio.playTestTone());
    assert(!audio.playPcm(pcm, sizeof(pcm)));
  }
  writeMode = 0;
  queuedBlocks = 7;
  assert(audio.recordThreeSeconds(pcm, sizeof(pcm)));
  assert(readSample == Config::MIC_DMA_WORDS + Config::AUDIO_SAMPLES);
  for (size_t i = 0; i < Config::AUDIO_SAMPLES; ++i) {
    int32_t expected = (rawSample(i + Config::MIC_DMA_WORDS) >> 16) * Config::MIC_GAIN;
    if (expected > 32767) expected = 32767;
    if (expected < -32768) expected = -32768;
    int16_t value;
    memcpy(&value, pcm + i * 2, 2);
    assert(value == expected);
  }
  output.clear();
  assert(audio.playPcm(pcm, sizeof(pcm)));
  assert(output.size() == (Config::AUDIO_SAMPLES + 64 + tail) * 2);
  assert((output.size() / 2) % Config::I2S_DMA_FRAMES == 0);
  for (size_t i = 0; i < Config::AUDIO_SAMPLES; ++i) {
    int16_t value; memcpy(&value, pcm + i * 2, 2);
    assert(output[i * 2] == value && output[i * 2 + 1] == value);
  }
  for (size_t i = Config::AUDIO_SAMPLES * 2; i < output.size(); ++i) assert(output[i] == 0);
  stalledRead = true;
  assert(!audio.recordThreeSeconds(pcm, sizeof(pcm)));
  stalledRead = false;
  queuedBlocks = 100;  // A queue that never drains must fail within a fixed bound.
  assert(!audio.recordThreeSeconds(pcm, sizeof(pcm)));
  queuedBlocks = 0;
  assert(!audio.recordThreeSeconds(nullptr, sizeof(pcm)));
  assert(!audio.recordThreeSeconds(pcm, sizeof(pcm) - 1));
  assert(!audio.playPcm(nullptr, sizeof(pcm)));
  assert(!audio.playPcm(pcm, sizeof(pcm) - 1));
  assert(!audio.playTestTone(0) && !audio.playTestTone(15001));
  audio.stopSpeaker();
  assert(running && starts == 1 && stops == 1 && enables == 1);
  assert(audio.begin());
  assert(starts == 1 && stops == 1 && enables == 1);
  freshHardware();
  failedPort = I2S_NUM_0;
  AudioManager speakerOnly;
  assert(!speakerOnly.begin() && !speakerOnly.microphoneReady() && speakerOnly.speakerReady());
  assert(speakerOnly.playTestTone());
  freshHardware();
  failedPinPort = I2S_NUM_1;
  AudioManager pinFailure;
  assert(!pinFailure.begin() && pinFailure.microphoneReady() && !pinFailure.speakerReady());
  assert(uninstallCount == 1);
  assert(!running && !installed && !routed && levels[Pins::SPK_SD] == 0);
  freshHardware();
  failedPort = I2S_NUM_1;
  AudioManager installFailure;
  assert(!installFailure.begin() && installFailure.microphoneReady() && !installFailure.speakerReady());
  assert(!running && !installed && levels[Pins::SPK_SD] == 0 && uninstallCount == 0);
  for (auto fault : {InitFault::GpioBclkHigh, InitFault::GpioWsHigh, InitFault::Pull}) {
    freshHardware();
    initFault = fault;
    AudioManager failure;
    assert(!failure.begin() && failure.microphoneReady() && !failure.speakerReady());
    assert(!installed && !running && !routed && levels[Pins::SPK_SD] == 0);
    assert(uninstallCount == 0 && enables == 0 && !failure.playTestTone());
  }
  for (auto fault : {InitFault::Stop, InitFault::Clear, InitFault::Monitor,
#if !defined(CONFIG_IDF_TARGET_ESP32S3)
                    InitFault::BclkHigh, InitFault::WsHigh,
#endif
                    InitFault::Enable, InitFault::Start}) {
    freshHardware();
    initFault = fault;
    AudioManager failure;
    assert(!failure.begin() && failure.microphoneReady() && !failure.speakerReady());
    assert(!installed && !running && !routed && levels[Pins::SPK_SD] == 0);
    assert(uninstallCount == 1 && !failure.playTestTone());
    const auto failedAt = timeUs;
    assert(!failure.begin() && timeUs == failedAt); // Reset required; no unsafe retry.
  }
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  puts("PASS: S3 32-bit wire samples / 512 kHz BCLK, WS-high idle, clocks-before-enable sequencing");
#endif
  puts("PASS: amp startup ordering/delay, continuous clocks, idempotence, fail-closed cleanup");
  puts("PASS: audio stereo/tone samples, partial/failed I/O, capture queue, conversion/clipping, buffer guards, init isolation");
}
