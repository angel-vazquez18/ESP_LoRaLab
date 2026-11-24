#pragma once

#include "radio_frame.h"

// One GCM envelope descriptor is carried over LoRa before the unchanged 200
// data frames. Header/length are authenticated as AAD; nonce/tag are public.
namespace CryptoRadioFrame {
constexpr uint8_t META_MAGIC = 0xFB;
constexpr uint8_t META_VERSION = 1;
constexpr uint8_t META_ACK_INDEX = 255;
constexpr size_t AAD_BYTES = 8;
constexpr size_t NONCE_BYTES = 12;
constexpr size_t GCM_TAG_BYTES = 16;
constexpr size_t META_BYTES = AAD_BYTES + NONCE_BYTES + GCM_TAG_BYTES + 4;
constexpr size_t NONCE_OFFSET = AAD_BYTES;
constexpr size_t TAG_OFFSET = NONCE_OFFSET + NONCE_BYTES;
constexpr size_t CRC_OFFSET = TAG_OFFSET + GCM_TAG_BYTES;
static_assert(META_BYTES == 40, "GCM metadata is exactly 40 radio-payload bytes");

inline void encodeAad(uint16_t id, uint8_t* out) {
  out[0] = META_MAGIC;
  out[1] = META_VERSION;
  RadioFrame::Detail::write16(out + 2, id);
  RadioFrame::Detail::write32(out + 4, Config::AUDIO_BUFFER_BYTES);
}

inline bool encodeMetadata(uint16_t id, const uint8_t* nonce, const uint8_t* tag,
                           uint8_t* out, size_t capacity) {
  if (!id || !nonce || !tag || !out || capacity < META_BYTES) return false;
  encodeAad(id, out);
  memcpy(out + NONCE_OFFSET, nonce, NONCE_BYTES);
  memcpy(out + TAG_OFFSET, tag, GCM_TAG_BYTES);
  RadioFrame::Detail::write32(out + CRC_OFFSET, AudioDiagnostics::crc32(out, CRC_OFFSET));
  return true;
}

inline bool validMetadata(const uint8_t* raw, size_t length, uint16_t expectedId) {
  if (!raw || length != META_BYTES || !expectedId) return false;
  return raw[0] == META_MAGIC && raw[1] == META_VERSION &&
         RadioFrame::Detail::read16(raw + 2) == expectedId &&
         RadioFrame::Detail::read32(raw + 4) == Config::AUDIO_BUFFER_BYTES &&
         RadioFrame::Detail::read32(raw + CRC_OFFSET) == AudioDiagnostics::crc32(raw, CRC_OFFSET);
}

inline uint32_t metadataCrc(const uint8_t* raw) {
  return RadioFrame::Detail::read32(raw + CRC_OFFSET);
}

inline bool decodeMetadataAck(const uint8_t* raw, size_t length,
                              uint16_t expectedId, uint32_t expectedCrc) {
  if (!raw || length != RadioFrame::ACK_BYTES || !expectedId) return false;
  return raw[0] == RadioFrame::ACK_MAGIC && raw[1] == RadioFrame::ACK_VERSION &&
         RadioFrame::Detail::read16(raw + 2) == expectedId && raw[4] == META_ACK_INDEX &&
         raw[5] == 0 && RadioFrame::Detail::read32(raw + 6) == expectedCrc &&
         RadioFrame::Detail::read32(raw + 10) == AudioDiagnostics::crc32(raw, 10);
}
}  // namespace CryptoRadioFrame
