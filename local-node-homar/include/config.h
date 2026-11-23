#pragma once

#include <stddef.h>
#include <stdint.h>

namespace Config {

#ifndef AUDIO_ENABLE_MIC
#define AUDIO_ENABLE_MIC 1
#endif
#ifndef AUDIO_ENABLE_SPEAKER
#define AUDIO_ENABLE_SPEAKER 1
#endif

constexpr bool ENABLE_MIC = AUDIO_ENABLE_MIC != 0;
constexpr bool ENABLE_SPEAKER = AUDIO_ENABLE_SPEAKER != 0;
constexpr bool ENABLE_PTT = false;  // Deferred until actual LoRa transport is verified.

// -----------------------------------------------------------------------------
// Audio format.
// -----------------------------------------------------------------------------

constexpr uint32_t AUDIO_SAMPLE_RATE_HZ = 8000;
constexpr uint16_t AUDIO_BITS_PER_SAMPLE = 16;
constexpr uint8_t AUDIO_CHANNELS = 1;
constexpr uint32_t RECORD_SECONDS = 3;

// 8000 samples/sec × 3 seconds = 24000 samples.
// 24000 samples × 2 bytes/sample = 48000 bytes.
constexpr size_t AUDIO_SAMPLES =
    AUDIO_SAMPLE_RATE_HZ * RECORD_SECONDS;

constexpr size_t AUDIO_BUFFER_BYTES =
    AUDIO_SAMPLES * (AUDIO_BITS_PER_SAMPLE / 8);

static_assert(AUDIO_BUFFER_BYTES == 48000,
              "Audio buffer must be exactly 48,000 bytes");

// -----------------------------------------------------------------------------
// Voice protocol.
// -----------------------------------------------------------------------------

constexpr uint8_t VOICE_PROTOCOL_MAGIC = 0xF9;
constexpr uint8_t VOICE_PROTOCOL_VERSION = 0x01;

// Header is:
//   magic         1 byte
//   version       1 byte
//   messageId     2 bytes
//   chunkIndex    1 byte
//   totalChunks   1 byte
//   payloadLength 1 byte
constexpr size_t VOICE_HEADER_BYTES = 7;

// 48,000 / 240 = exactly 200 chunks.
constexpr size_t VOICE_CHUNK_PAYLOAD_BYTES = 240;
constexpr uint8_t VOICE_TOTAL_CHUNKS =
    AUDIO_BUFFER_BYTES / VOICE_CHUNK_PAYLOAD_BYTES;

constexpr size_t VOICE_PACKET_BYTES =
    VOICE_HEADER_BYTES + VOICE_CHUNK_PAYLOAD_BYTES;

static_assert(VOICE_TOTAL_CHUNKS == 200,
              "Expected exactly 200 chunks");

static_assert(VOICE_PACKET_BYTES == 247,
              "Expected 247-byte final voice packet");

// -----------------------------------------------------------------------------
// Audio configuration.
// -----------------------------------------------------------------------------

// INMP441 usually provides 24-bit PCM in a 32-bit I2S slot.
// Shift by 16 converts the high 16 bits to signed 16-bit PCM.
//
// Increase this only after validating that audio does not clip.
// 1 = no gain.
// 2 = +6 dB approximate gain.
constexpr int32_t MIC_GAIN = 2;

// Number of 32-bit samples read per I2S transaction.
constexpr size_t MIC_DMA_WORDS = 128;
constexpr size_t I2S_DMA_BUFFERS = 8;
constexpr size_t I2S_DMA_FRAMES = 128;
constexpr uint32_t I2S_TIMEOUT_MS = 250;

// Original ESP32 uses 256 kHz BCLK: enable must precede clocks by >=10 us.
// Heltec/S3 uses 32-bit speaker slots at 512 kHz, with silent clocks established
// before amplifier enable. Stored/captured PCM remains 16-bit for both boards.
// VIN must already be valid; this firmware does not sense VIN.
constexpr uint32_t AMP_SHUTDOWN_US = 1000;
constexpr uint32_t AMP_ENABLE_TO_CLOCK_US = 20;
constexpr uint32_t AMP_STARTUP_SETTLE_MS = 20;
static_assert(AMP_ENABLE_TO_CLOCK_US >= 10, "MAX98357A enable delay too short");

// -----------------------------------------------------------------------------
// Simulated packet transport.
// -----------------------------------------------------------------------------
//
// This bench does not initialize or use a radio, including the Heltec SX1262.
// It creates packets from TX PCM,
// optionally drops packets, and feeds packets into the RX reassembler.
//
// 0 = no intentionally dropped packets.
// Example: 17 means every 17th packet is dropped.
//
// With 0, PTT should record then play back normally.
// With 17, approximately 11-12 chunks will be missing and become silence.
constexpr uint8_t SIMULATED_DROP_EVERY_N = 0;

}  // namespace Config
