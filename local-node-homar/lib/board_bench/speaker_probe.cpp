#include "board_bench.h"

#include <Arduino.h>

#if defined(AUDIO_BOARD_HELTEC_V4) && AUDIO_BOARD_HELTEC_V4

#include <driver/gpio.h>
#include <driver/pulse_cnt.h>
#include <esp_timer.h>
#include <memory>
#include <new>

#include "pins.h"

namespace {

constexpr int COUNTER_LIMIT = 30000;
constexpr int64_t MAX_WINDOW_US = 50000;

bool probeResult(esp_err_t result, const char* operation) {
  if (result == ESP_OK) return true;
  Serial.printf("[PINS] ERROR: %s: %s (%d)\n", operation,
                esp_err_to_name(result), static_cast<int>(result));
  return false;
}

// IDF 5.5.5 PCNT channel setup appends input routing without changing GPIO
// direction or the output-matrix signal. Channel deletion removes only that
// PCNT input route. Both operations change pulls, so restore our low-idle pull.
// Do not use gpio_reset_pin(), gpio_set_direction(), or pinMode(INPUT) here.
class SignalCounter {
 public:
  SignalCounter(gpio_num_t pin, const char* role) : pin_(pin), role_(role) {}
  ~SignalCounter() { release(); }
  SignalCounter(const SignalCounter&) = delete;
  SignalCounter& operator=(const SignalCounter&) = delete;

  bool prepare() {
    pcnt_unit_config_t config = {};
    config.low_limit = -COUNTER_LIMIT;
    config.high_limit = COUNTER_LIMIT;
    // Accumulate limit events rather than silently wrapping if the observed
    // clock is unexpectedly fast. Still reject a delayed sampling window.
    config.flags.accum_count = true;
    if (!probeResult(pcnt_new_unit(&config, &unit_), "create signal counter")) return false;
    if (!probeResult(pcnt_unit_add_watch_point(unit_, -COUNTER_LIMIT), "watch counter low limit") ||
        !probeResult(pcnt_unit_add_watch_point(unit_, COUNTER_LIMIT), "watch counter high limit")) {
      return false;
    }
    pcnt_chan_config_t channelConfig = {};
    channelConfig.edge_gpio_num = pin_;
    channelConfig.level_gpio_num = -1;
    if (!probeResult(pcnt_new_channel(unit_, &channelConfig, &channel_), "attach signal input")) return false;
    pinTouched_ = true;
    if (!probeResult(gpio_set_pull_mode(pin_, GPIO_PULLDOWN_ONLY), "restore signal pull after attach") ||
        !probeResult(pcnt_channel_set_edge_action(channel_, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                                PCNT_CHANNEL_EDGE_ACTION_HOLD), "count rising edges") ||
        !probeResult(pcnt_channel_set_level_action(channel_, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                                 PCNT_CHANNEL_LEVEL_ACTION_KEEP), "ignore counter level input") ||
        !probeResult(pcnt_unit_clear_count(unit_), "clear signal count")) {
      return false;
    }
    if (!probeResult(pcnt_unit_enable(unit_), "enable signal counter")) return false;
    enabled_ = true;
    return true;
  }

  bool start() {
    startUs_ = esp_timer_get_time();
    if (!probeResult(pcnt_unit_start(unit_), "start signal counter")) return false;
    running_ = true;
    return true;
  }

  bool stop() {
    if (!probeResult(pcnt_unit_stop(unit_), "stop signal counter")) return false;
    endUs_ = esp_timer_get_time();
    running_ = false;
    return true;
  }

  void report() const {
    int count = 0;
    if (!probeResult(pcnt_unit_get_count(unit_, &count), "read clock count")) return;
    const int64_t elapsedUs = endUs_ - startUs_;
    if (elapsedUs <= 0 || elapsedUs > MAX_WINDOW_US || count < 0) {
      Serial.printf("[PINS] %s GPIO%d rising_edges=%d elapsed_us=%lld approx_hz=unavailable\n",
                    role_, static_cast<int>(pin_), count, static_cast<long long>(elapsedUs));
      Serial.println("[PINS] ERROR: clock sampling window/count invalid; repeat the probe");
      return;
    }
    const double frequency = static_cast<double>(count) * 1000000.0 / elapsedUs;
    Serial.printf("[PINS] %s GPIO%d rising_edges=%d elapsed_us=%lld approx_hz=%.1f\n",
                  role_, static_cast<int>(pin_), count, static_cast<long long>(elapsedUs), frequency);
  }

  void reportActivity() const {
    int count = 0;
    if (!probeResult(pcnt_unit_get_count(unit_, &count), "read signal activity count")) return;
    const int64_t elapsedUs = endUs_ - startUs_;
    if (elapsedUs <= 0 || count < 0) {
      Serial.println("[PINS] ERROR: invalid tone activity sampling window/count");
      return;
    }
    // DIN is encoded serial audio, not the 1 kHz acoustic waveform. Its edge
    // count confirms activity only; never interpret it as a tone frequency.
    Serial.printf("[PINS] %s GPIO%d rising_edges=%d elapsed_us=%lld\n",
                  role_, static_cast<int>(pin_), count, static_cast<long long>(elapsedUs));
    Serial.println("[PINS] DIN activity only: no tone frequency or amplifier-terminal continuity inferred");
  }

 private:
  void release() {
    if (running_ && probeResult(pcnt_unit_stop(unit_), "cleanup stop counter")) running_ = false;
    if (enabled_ && probeResult(pcnt_unit_disable(unit_), "cleanup disable counter")) enabled_ = false;
    if (channel_ && !enabled_ && probeResult(pcnt_del_channel(channel_), "cleanup delete channel")) {
      channel_ = nullptr;
    }
    if (unit_ && !enabled_ && !channel_ && probeResult(pcnt_del_unit(unit_), "cleanup delete counter")) {
      unit_ = nullptr;
    }
    if (pinTouched_) {
      probeResult(gpio_set_pull_mode(pin_, GPIO_PULLDOWN_ONLY), "restore signal pull after cleanup");
    }
  }

  gpio_num_t pin_;
  const char* role_;
  pcnt_unit_handle_t unit_ = nullptr;
  pcnt_channel_handle_t channel_ = nullptr;
  bool enabled_ = false;
  bool running_ = false;
  bool pinTouched_ = false;
  int64_t startUs_ = 0;
  int64_t endUs_ = 0;
};

// Only the synchronous serial 's' command uses this probe. Resetting the owner
// releases the PCNT channel/unit on setup failures and after every tone.
std::unique_ptr<SignalCounter> toneCounter;

void probeSpeakerPins() {
  if (probeResult(gpio_input_enable(Pins::SPK_SD), "enable SD input readback")) {
    Serial.printf("[PINS] SD GPIO%d=%d\n", static_cast<int>(Pins::SPK_SD), gpio_get_level(Pins::SPK_SD));
  }
  SignalCounter bclk(Pins::SPK_BCLK, "BCLK");
  SignalCounter ws(Pins::SPK_WS, "LRC");
  if (!bclk.prepare() || !ws.prepare()) return;
  if (!bclk.start() || !ws.start()) return;
  delay(20);
  // Stop both even if one API reports an error. Destructors handle all exits.
  const bool bclkStopped = bclk.stop();
  const bool wsStopped = ws.stop();
  if (bclkStopped) bclk.report();
  if (wsStopped) ws.report();
}

}  // namespace

#endif

namespace BoardBench {

void beginToneProbe() {
#if defined(AUDIO_BOARD_HELTEC_V4) && AUDIO_BOARD_HELTEC_V4
  Serial.println("[DIN] BEGIN");
  toneCounter.reset(new (std::nothrow) SignalCounter(Pins::SPK_DOUT, "DIN"));
  if (!toneCounter) {
    Serial.println("[PINS] ERROR: allocate tone activity probe");
    return;
  }
  if (!toneCounter->prepare() || !toneCounter->start()) toneCounter.reset();
#endif
}

void endToneProbe() {
#if defined(AUDIO_BOARD_HELTEC_V4) && AUDIO_BOARD_HELTEC_V4
  if (toneCounter) {
    if (toneCounter->stop()) toneCounter->reportActivity();
    toneCounter.reset();
  } else {
    Serial.println("[PINS] ERROR: tone activity measurement unavailable");
  }
  Serial.println("[DIN] END");
#endif
}

void printSpeakerPins() {
  Serial.println("[PINS] BEGIN");
#if defined(AUDIO_BOARD_HELTEC_V4) && AUDIO_BOARD_HELTEC_V4
  probeSpeakerPins();
  Serial.println("[PINS] MCU pad readback only; this does not verify amplifier-terminal voltage or wire continuity");
#else
  Serial.println("[PINS] Speaker pin probe is available only on the Heltec V4 bench");
#endif
  Serial.println("[PINS] END");
}

}  // namespace BoardBench
