#include "audio_manager.h"

#include <Arduino.h>
#include <driver/gpio.h>
#include <driver/i2s.h>
#include <hal/i2s_ll.h>
#include <math.h>
#include <string.h>

#include "config.h"
#include "pins.h"
#include "audio_diagnostics.h"

namespace {

constexpr i2s_port_t MIC_I2S_PORT = I2S_NUM_0;
constexpr i2s_port_t SPK_I2S_PORT = I2S_NUM_1;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
// A 64-clock stereo frame keeps BCLK above MAX98357A's special 256 kHz mode.
constexpr auto SPK_SAMPLE_BITS = I2S_BITS_PER_SAMPLE_32BIT;
constexpr size_t SPK_SAMPLE_BYTES = sizeof(int32_t);
#else
constexpr auto SPK_SAMPLE_BITS = I2S_BITS_PER_SAMPLE_16BIT;
constexpr size_t SPK_SAMPLE_BYTES = sizeof(int16_t);
#endif
constexpr size_t SPK_FRAME_BYTES = 2 * SPK_SAMPLE_BYTES;
constexpr uint32_t SPK_BCLK_HZ = Config::AUDIO_SAMPLE_RATE_HZ * SPK_FRAME_BYTES * 8;

bool checkI2s(esp_err_t result, const char* operation) {
  if (result == ESP_OK) return true;
  Serial.printf("[I2S] %s failed: %s (%d)\n", operation,
                esp_err_to_name(result), result);
  return false;
}

bool outputLow(gpio_num_t pin) {
  // gpio_reset_pin disconnects a previous GPIO-matrix peripheral route.
  // It also enables a pull-up: replace that with a pull-down so a stopped
  // peripheral releasing its output cannot pull an amplifier input high.
  return checkI2s(gpio_reset_pin(pin), "GPIO reset") &&
         checkI2s(gpio_set_pull_mode(pin, GPIO_PULLDOWN_ONLY), "GPIO idle pulldown") &&
         checkI2s(gpio_set_level(pin, 0), "GPIO preload low") &&
         checkI2s(gpio_set_direction(pin, GPIO_MODE_OUTPUT), "GPIO output");
}

bool speakerBusLow() {
  // The legacy driver auto-starts on install. Until explicitly stopped/reset,
  // its clocks must remain disconnected from these amplifier inputs.
  const bool bclk = outputLow(Pins::SPK_BCLK);
  const bool ws = outputLow(Pins::SPK_WS);
  const bool data = outputLow(Pins::SPK_DOUT);
  return bclk && ws && data;
}

bool readSpeakerClockPads(const char* phase, int& bclk, int& ws) {
  if (!checkI2s(gpio_input_enable(Pins::SPK_BCLK), "BCLK input monitor") ||
      !checkI2s(gpio_input_enable(Pins::SPK_WS), "LRC input monitor")) {
    return false;
  }
  bclk = gpio_get_level(Pins::SPK_BCLK);
  ws = gpio_get_level(Pins::SPK_WS);
  Serial.printf("[AMP] %s pads: BCLK=%d LRC=%d\n", phase, bclk, ws);
  return true;
}

bool speakerClockPadsLow(const char* phase) {
  int bclk = 0, ws = 0;
  return readSpeakerClockPads(phase, bclk, ws) && bclk == 0 && ws == 0;
}

bool discardSpeakerDriver() {
  // Shutdown BEFORE stopping clocks (including failures after i2s_start).
  checkI2s(gpio_set_level(Pins::SPK_SD, 0), "amp shutdown on failure");
  delayMicroseconds(Config::AMP_SHUTDOWN_US);
  checkI2s(i2s_driver_uninstall(SPK_I2S_PORT), "speaker uninstall");
  speakerBusLow();
  return false;
}

// Small, bounded transactions: ESP_OK alone does not imply bytes were moved.
bool writeSpeaker(const int16_t* stereo, size_t frames) {
  if (frames > Config::I2S_DMA_FRAMES) return false;
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  // Storage and packet PCM stay 16-bit. Promote only the bounded I2S write
  // block, placing its signed samples in the high 16 bits of each wire slot.
  // Multiplication is defined for negative samples, unlike signed left shift.
  int32_t wireSamples[Config::I2S_DMA_FRAMES * 2];
  for (size_t i = 0; i < frames * 2; ++i) {
    wireSamples[i] = static_cast<int32_t>(stereo[i]) * 65536;
  }
  const auto* bytes = reinterpret_cast<const uint8_t*>(wireSamples);
#else
  const auto* bytes = reinterpret_cast<const uint8_t*>(stereo);
#endif
  const size_t length = frames * SPK_FRAME_BYTES;
  size_t offset = 0;
  while (offset < length) {
    size_t written = 0;
    const esp_err_t result = i2s_write(SPK_I2S_PORT, bytes + offset,
        length - offset, &written, pdMS_TO_TICKS(Config::I2S_TIMEOUT_MS));
    if (!checkI2s(result, "speaker write") || written == 0 ||
        written > length - offset || written % SPK_FRAME_BYTES != 0) {
      Serial.printf("[I2S] Speaker stalled/invalid transfer: %u bytes\n",
                    static_cast<unsigned>(written));
      return false;
    }
    offset += written;
  }
  return true;
}

bool finishSpeaker() {
  // i2s_write queues data; it does not wait for the last sample on the wire.
  // Queue more than a full DMA ring of silence before clearing it. This also
  // covers a partially filled final descriptor without cutting off the audio.
  const int16_t silence[Config::I2S_DMA_FRAMES * 2] = {};
  for (size_t i = 0; i < Config::I2S_DMA_BUFFERS + 1; ++i) {
    if (!writeSpeaker(silence, Config::I2S_DMA_FRAMES)) return false;
  }
  return checkI2s(i2s_zero_dma_buffer(SPK_I2S_PORT), "speaker clear");
}

bool readMicrophone(int32_t* words, size_t requestedWords, size_t& wordsRead) {
  size_t bytesRead = 0;
  const esp_err_t result = i2s_read(MIC_I2S_PORT, words,
      requestedWords * sizeof(int32_t), &bytesRead,
      pdMS_TO_TICKS(Config::I2S_TIMEOUT_MS));
  if (!checkI2s(result, "microphone read") || bytesRead == 0 ||
      bytesRead > requestedWords * sizeof(int32_t) || bytesRead % 4 != 0) {
    Serial.printf("[I2S] Microphone stalled/invalid transfer: %u bytes\n",
                  static_cast<unsigned>(bytesRead));
    return false;
  }
  wordsRead = bytesRead / sizeof(int32_t);
  return true;
}

bool discardQueuedMicrophone(int32_t* scratch) {
  // Keep microphone clocks running. Zeroing DMA memory does not empty the
  // legacy driver's RX queue and can introduce ~128 ms of stale/zero audio.
  for (size_t i = 0; i < Config::I2S_DMA_BUFFERS + 4; ++i) {
    size_t bytesRead = 0;
    if (!checkI2s(i2s_read(MIC_I2S_PORT, scratch,
            Config::MIC_DMA_WORDS * sizeof(int32_t), &bytesRead, 0),
            "microphone discard")) return false;
    if (bytesRead == 0) {
      // Discard one fresh descriptor as well: it may have started before
      // the command. The following 24,000 samples form the new recording.
      size_t wordsRead = 0;
      return readMicrophone(scratch, Config::MIC_DMA_WORDS, wordsRead) &&
             wordsRead == Config::MIC_DMA_WORDS;
    }
  }
  Serial.println("[I2S] Could not drain microphone queue");
  return false;
}

int16_t saturateToInt16(int32_t value) {
  if (value > 32767) {
    return 32767;
  }

  if (value < -32768) {
    return -32768;
  }

  return static_cast<int16_t>(value);
}

}  // namespace

bool AudioManager::begin() {
  // Repeated begin() must not interrupt an already enabled speaker bus.
  // A failed initialization requires a board reset, not an unsequenced retry.
  if (beginCalled_) return beginResult_;
  beginCalled_ = true;
  const bool shutdownReady = outputLow(Pins::SPK_SD);
  microphoneReady_ = Config::ENABLE_MIC && configureMicrophoneI2S();
  speakerReady_ = Config::ENABLE_SPEAKER && shutdownReady && configureSpeakerI2S();
  // INMP441 power-up mute is 2^18 BCLK cycles: ~512 ms at 512 kHz.
  // Keep its clocks running between commands and allow margin at startup.
  if (microphoneReady_) delay(600);
  beginResult_ = shutdownReady && (!Config::ENABLE_MIC || microphoneReady_) &&
                 (!Config::ENABLE_SPEAKER || speakerReady_);
  return beginResult_;
}

void AudioManager::printDiagnostics() const {
  Serial.printf("[I2S] MIC requested=%u ready=%u, SPK requested=%u ready=%u\n",
      Config::ENABLE_MIC, microphoneReady_, Config::ENABLE_SPEAKER, speakerReady_);
  Serial.printf("[I2S] MIC BCLK=%d WS=%d SD=%d, left 32-bit; nominal 512 kHz / 8 kHz\n",
      Pins::MIC_BCLK, Pins::MIC_WS, Pins::MIC_SD);
  Serial.printf("[I2S] SPK BCLK=%d LRC=%d DIN=%d, L=R %u-bit wire slots; nominal %lu Hz / %lu Hz\n",
      Pins::SPK_BCLK, Pins::SPK_WS, Pins::SPK_DOUT,
      static_cast<unsigned>(SPK_SAMPLE_BYTES * 8),
      static_cast<unsigned long>(SPK_BCLK_HZ),
      static_cast<unsigned long>(Config::AUDIO_SAMPLE_RATE_HZ));
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  Serial.printf("[AMP] SD/MODE=GPIO%d; silent clocks settle %lu ms before enable; ready=%u\n",
      Pins::SPK_SD, static_cast<unsigned long>(Config::AMP_STARTUP_SETTLE_MS), speakerReady_);
#else
  Serial.printf("[AMP] SD/MODE=GPIO%d; startup enable-to-clock wait >=%lu us; ready=%u\n",
      Pins::SPK_SD, static_cast<unsigned long>(Config::AMP_ENABLE_TO_CLOCK_US), speakerReady_);
#endif
  Serial.printf("[AMP] SD/MODE connects to GPIO%d with a 1k pulldown to GND\n",
      Pins::SPK_SD);
  Serial.println("[AMP] Startup edge phase requires scope validation; ready is software status only");
  Serial.println("[I2S] Frequencies above are configured targets, not measurements; MCLK disabled");
}

bool AudioManager::configureMicrophoneI2S() {
  const i2s_config_t config = {
      .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = Config::AUDIO_SAMPLE_RATE_HZ,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = Config::I2S_DMA_BUFFERS,
      .dma_buf_len = Config::I2S_DMA_FRAMES,
      .use_apll = false,
      .tx_desc_auto_clear = false,
      .fixed_mclk = 0
  };

  i2s_pin_config_t pins = {};
      pins.mck_io_num = I2S_PIN_NO_CHANGE;
      pins.bck_io_num = Pins::MIC_BCLK;
      pins.ws_io_num = Pins::MIC_WS;
      pins.data_out_num = I2S_PIN_NO_CHANGE;
      pins.data_in_num = Pins::MIC_SD;

  const esp_err_t installResult =
      i2s_driver_install(MIC_I2S_PORT, &config, 0, nullptr);

  if (installResult != ESP_OK) {
    Serial.printf("MIC i2s_driver_install failed: %d\n", installResult);
    return false;
  }

  const esp_err_t pinResult =
      i2s_set_pin(MIC_I2S_PORT, &pins);

  if (pinResult != ESP_OK) {
    Serial.printf("MIC i2s_set_pin failed: %d\n", pinResult);
    i2s_driver_uninstall(MIC_I2S_PORT);
    return false;
  }

  return true;
}

bool AudioManager::configureSpeakerI2S() {
  // SD is already low. Give the amplifier a definite shutdown interval, and
  // drive BCLK/LRC/DIN low before installing the auto-starting legacy driver.
  delayMicroseconds(Config::AMP_SHUTDOWN_US);
  if (!speakerBusLow()) return false;
  if (!speakerClockPadsLow("GPIO-held-low")) {
    Serial.println("[AMP] Startup aborted: GPIO-held BCLK/LRC are not both low");
    return false;
  }
  const i2s_config_t config = {
      .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX),
      .sample_rate = Config::AUDIO_SAMPLE_RATE_HZ,
      .bits_per_sample = SPK_SAMPLE_BITS,
      // Duplicate mono PCM into both slots in software. SD channel selection
      // then cannot select an empty slot; also avoids ESP32 16-bit mono swaps.
      .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = Config::I2S_DMA_BUFFERS,
      .dma_buf_len = Config::I2S_DMA_FRAMES,
      .use_apll = false,
      .tx_desc_auto_clear = true,
      .fixed_mclk = 0
  };

  i2s_pin_config_t pins = {};
      pins.mck_io_num = I2S_PIN_NO_CHANGE;
      pins.bck_io_num = Pins::SPK_BCLK;
      pins.ws_io_num = Pins::SPK_WS;
      pins.data_out_num = Pins::SPK_DOUT;
      pins.data_in_num = I2S_PIN_NO_CHANGE;


  const esp_err_t installResult =
      i2s_driver_install(SPK_I2S_PORT, &config, 0, nullptr);

  if (installResult != ESP_OK) {
    Serial.printf("SPK i2s_driver_install failed: %d\n", installResult);
    return false;
  }

  if (!checkI2s(i2s_stop(SPK_I2S_PORT), "speaker stop before routing")) {
    return discardSpeakerDriver();
  }
  // Reset the stopped serializer before exposing its signals. The hardware
  // generates both clocks together. ESP32's 256 kHz mode additionally needs
  // low idle levels and its first rising-edge phase verified on a scope.
  auto* speakerHw = I2S_LL_GET_HW(SPK_I2S_PORT);
  i2s_ll_tx_reset(speakerHw);
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  // ESP32-S3 uses I2S hardware v2 and a continuous GDMA descriptor ring.
  // Its standard-mode WS polarity replaces the ESP32 right-first setting.
  // Latch APB configuration into the TX clock domain before checking idle
  // levels; the driver's usual update occurs later, inside i2s_start().
  i2s_ll_tx_set_ws_idle_pol(speakerHw, false);
  i2s_ll_tx_update(speakerHw);
#else
  i2s_ll_tx_enable_right_first(speakerHw, false);
  i2s_ll_tx_stop_on_fifo_empty(speakerHw, false);
#endif
  if (!checkI2s(i2s_zero_dma_buffer(SPK_I2S_PORT), "speaker init clear")) {
    return discardSpeakerDriver();
  }

  const esp_err_t pinResult =
      i2s_set_pin(SPK_I2S_PORT, &pins);

  if (pinResult != ESP_OK) {
    Serial.printf("SPK i2s_set_pin failed: %d\n", pinResult);
    return discardSpeakerDriver();
  }
  // The S3 serializer idles WS high. At 512 kHz the amplifier permits this:
  // start hardware-generated silent clocks while SD remains low, then enable
  // only after they have settled. The earlier GPIO-held-low check still
  // rejects a pad that cannot be driven low, including a physical short.
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  int bclk = 0, ws = 0;
  if (!readSpeakerClockPads("I2S-stopped (512 kHz mode)", bclk, ws)) {
    return discardSpeakerDriver();
  }
  if (!checkI2s(i2s_start(SPK_I2S_PORT), "speaker silent-clock start")) {
    return discardSpeakerDriver();
  }
  delay(Config::AMP_STARTUP_SETTLE_MS);
  if (!checkI2s(gpio_set_level(Pins::SPK_SD, 1), "amp enable after clocks")) {
    return discardSpeakerDriver();
  }
#else
  // MAX98357A's 256 kHz mode requires both clocks initially low, enable before
  // clocks, and a >=10 us delay. Preserve the validated ESP32 bench sequence.
  if (!speakerClockPadsLow("I2S-stopped")) {
    Serial.println("[AMP] Startup aborted: stopped BCLK/LRC are not both low");
    return discardSpeakerDriver();
  }
  if (!checkI2s(gpio_set_level(Pins::SPK_SD, 1), "amp enable")) {
    return discardSpeakerDriver();
  }
  delayMicroseconds(Config::AMP_ENABLE_TO_CLOCK_US);
  if (!checkI2s(i2s_start(SPK_I2S_PORT), "speaker sequenced start")) {
    return discardSpeakerDriver();
  }
#endif
  // All descriptors contain silence. Keep clocks running continuously from
  // here, including between tones, recordings and playback/error clears.
  delay(Config::AMP_STARTUP_SETTLE_MS);
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  Serial.println("[AMP] Silent I2S clocks started before SD enable; continuous 512 kHz / 8 kHz requested");
#else
  Serial.println("[AMP] SD enabled before I2S start; continuous 256 kHz / 8 kHz requested");
#endif
  return true;
}

bool AudioManager::recordThreeSeconds(uint8_t* destination,
                                      size_t destinationBytes) {
  if (!microphoneReady_ || destination == nullptr) {
    Serial.println("[AUDIO] Microphone unavailable or null record buffer");
    return false;
  }

  if (destinationBytes != Config::AUDIO_BUFFER_BYTES) {
    Serial.printf("Invalid record buffer size: %u\n",
                  static_cast<unsigned>(destinationBytes));
    return false;
  }

  int32_t microphoneWords[Config::MIC_DMA_WORDS];
  size_t samplesWritten = 0;
  if (!discardQueuedMicrophone(microphoneWords)) return false;
  int16_t minimum = 32767, maximum = -32768;
  int64_t sum = 0;
  uint64_t sumSquares = 0;
  size_t zeroSamples = 0, clippedSamples = 0;
  uint32_t rawPreview[8] = {};
  AudioDiagnostics::RawStats rawStats;

  while (samplesWritten < Config::AUDIO_SAMPLES) {
    size_t wordsRead = 0;
    const size_t remaining = Config::AUDIO_SAMPLES - samplesWritten;
    const size_t requested = remaining < Config::MIC_DMA_WORDS ? remaining : Config::MIC_DMA_WORDS;
    if (!readMicrophone(microphoneWords, requested, wordsRead)) return false;

    for (size_t i = 0;
         i < wordsRead && samplesWritten < Config::AUDIO_SAMPLES;
         ++i) {
      // INMP441 data normally occupies the upper bits of a 32-bit I2S slot.
      // Shift down to signed 16-bit PCM, then apply bounded gain.
      int32_t sample16 = microphoneWords[i] >> 16;
      sample16 *= Config::MIC_GAIN;
      rawStats.add(static_cast<uint32_t>(microphoneWords[i]));

      const int16_t pcm = saturateToInt16(sample16);
      // Byte buffers need not be aligned for int16_t accesses.
      memcpy(destination + samplesWritten * sizeof(pcm), &pcm, sizeof(pcm));
      if (samplesWritten < 8) rawPreview[samplesWritten] = static_cast<uint32_t>(microphoneWords[i]);
      ++samplesWritten;
      if (pcm < minimum) minimum = pcm;
      if (pcm > maximum) maximum = pcm;
      sum += pcm;
      sumSquares += static_cast<int64_t>(pcm) * pcm;
      if (pcm == 0) ++zeroSamples;
      if (sample16 > 32767 || sample16 < -32768) ++clippedSamples;
    }
  }

  const double mean = static_cast<double>(sum) / samplesWritten;
  const double variance = static_cast<double>(sumSquares) / samplesWritten - mean * mean;
  Serial.printf("[MIC] samples=%u min=%d max=%d mean=%.1f AC_RMS=%.1f zero=%u clipped=%u\n",
      static_cast<unsigned>(samplesWritten), minimum, maximum, mean,
      sqrt(variance > 0 ? variance : 0), static_cast<unsigned>(zeroSamples),
      static_cast<unsigned>(clippedSamples));
  Serial.print("[MIC] First raw 32-bit slots:");
  for (uint32_t word : rawPreview) Serial.printf(" %08lx", static_cast<unsigned long>(word));
  Serial.println();
  Serial.printf("[MIC RAW] zero_words=%u all_one_words=%u longest_identical_run=%u / %u\n",
      static_cast<unsigned>(rawStats.zeros), static_cast<unsigned>(rawStats.ones),
      static_cast<unsigned>(rawStats.longestRun), static_cast<unsigned>(rawStats.count));
  return true;
}

bool AudioManager::playPcm(const uint8_t* source,
                           size_t sourceBytes) {
  if (!speakerReady_ || source == nullptr) {
    Serial.println("[AUDIO] Speaker unavailable or null playback buffer");
    return false;
  }

  if (sourceBytes != Config::AUDIO_BUFFER_BYTES) {
    Serial.printf("Invalid playback buffer size: %u\n",
                  static_cast<unsigned>(sourceBytes));
    return false;
  }

  if (!checkI2s(i2s_zero_dma_buffer(SPK_I2S_PORT), "speaker clear")) return false;
  int16_t stereo[Config::I2S_DMA_FRAMES * 2];
  size_t offset = 0;
  while (offset < sourceBytes) {
    const size_t remainingFrames = (sourceBytes - offset) / sizeof(int16_t);
    const size_t frames = remainingFrames < Config::I2S_DMA_FRAMES ? remainingFrames : Config::I2S_DMA_FRAMES;
    for (size_t i = 0; i < frames; ++i) {
      int16_t pcm;
      memcpy(&pcm, source + offset + i * sizeof(pcm), sizeof(pcm));
      stereo[2 * i] = stereo[2 * i + 1] = pcm;
    }
    // Finish on a DMA descriptor boundary. Clearing the legacy driver's DMA
    // memory does not reset its write cursor; a partial descriptor can become
    // stale while idle and lose the beginning of the next playback.
    for (size_t i = frames; i < Config::I2S_DMA_FRAMES; ++i) {
      stereo[2 * i] = stereo[2 * i + 1] = 0;
    }
    if (!writeSpeaker(stereo, Config::I2S_DMA_FRAMES)) { stopSpeaker(); return false; }
    offset += frames * sizeof(int16_t);
  }
  const bool finished = finishSpeaker();
  if (!finished) stopSpeaker();
  return finished;
}

void AudioManager::stopSpeaker() {
  // This aborts queued AUDIO, not the clocks or SD. Keep the bus continuous
  // on both targets; the ESP32's 256 kHz mode requires that ordering.
  if (speakerReady_) checkI2s(i2s_zero_dma_buffer(SPK_I2S_PORT), "speaker abort");
}

bool AudioManager::playTestTone(uint32_t durationMs) {
  if (!speakerReady_ || durationMs == 0 || durationMs > 15000) return false;
  if (!checkI2s(i2s_zero_dma_buffer(SPK_I2S_PORT), "tone clear")) return false;
  // 1 kHz square wave, modest digital level, identical left/right slots.
  // Generate an exact sample count; wall-clock enqueue time is not duration.
  constexpr int16_t AMPLITUDE = 2000;
  int16_t stereo[Config::I2S_DMA_FRAMES * 2];
  const size_t totalFrames = Config::AUDIO_SAMPLE_RATE_HZ * durationMs / 1000;
  size_t sent = 0;
  while (sent < totalFrames) {
    const size_t remaining = totalFrames - sent;
    const size_t frames = remaining < Config::I2S_DMA_FRAMES ? remaining : Config::I2S_DMA_FRAMES;
    for (size_t i = 0; i < frames; ++i) {
      const int16_t pcm = ((sent + i) % 8 < 4) ? AMPLITUDE : -AMPLITUDE;
      stereo[2 * i] = stereo[2 * i + 1] = pcm;
    }
    // Preserve the exact tone length, then pad only the final descriptor with
    // silence so the next command obtains a fresh DMA buffer after idle.
    for (size_t i = frames; i < Config::I2S_DMA_FRAMES; ++i) {
      stereo[2 * i] = stereo[2 * i + 1] = 0;
    }
    if (!writeSpeaker(stereo, Config::I2S_DMA_FRAMES)) { stopSpeaker(); return false; }
    sent += frames;
  }
  const bool finished = finishSpeaker();
  if (!finished) stopSpeaker();
  return finished;
}
