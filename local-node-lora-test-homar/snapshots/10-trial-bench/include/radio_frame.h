#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "audio_diagnostics.h"
#include "chunker.h"

namespace RadioFrame {

constexpr size_t DATA_BYTES = Config::VOICE_PACKET_BYTES + sizeof(uint32_t);
constexpr size_t ACK_BYTES = 14;
constexpr uint8_t ACK_MAGIC = 0xFA;
constexpr uint8_t ACK_VERSION = 1;
static_assert(DATA_BYTES == 251, "Radio data frame must remain 251 bytes");

namespace Detail {

inline void write16(uint8_t* out, uint16_t value) {
  out[0] = static_cast<uint8_t>(value);
  out[1] = static_cast<uint8_t>(value >> 8);
}

inline void write32(uint8_t* out, uint32_t value) {
  for (size_t i = 0; i < 4; ++i) out[i] = static_cast<uint8_t>(value >> (8 * i));
}

inline uint16_t read16(const uint8_t* raw) {
  return static_cast<uint16_t>(raw[0]) | (static_cast<uint16_t>(raw[1]) << 8);
}

inline uint32_t read32(const uint8_t* raw) {
  uint32_t value = 0;
  for (size_t i = 0; i < 4; ++i) value |= static_cast<uint32_t>(raw[i]) << (8 * i);
  return value;
}

}  // namespace Detail

// CRC covers the complete 247-byte VoicePacket. Its four bytes are appended
// little-endian; the existing voice header/payload layout is unchanged.
// pcm must contain Config::AUDIO_BUFFER_BYTES readable bytes.
inline bool encodeData(const uint8_t* pcm, uint16_t messageId, uint8_t index,
                       uint8_t* out, size_t capacity) {
  if (out == nullptr || capacity < DATA_BYTES) return false;
  VoicePacket packet;
  if (!VoiceChunker::makePacketFromBuffer(pcm, messageId, index, packet)) return false;
  out[0] = packet.header.magic;
  out[1] = packet.header.version;
  Detail::write16(out + 2, packet.header.messageId);
  out[4] = packet.header.chunkIndex;
  out[5] = packet.header.totalChunks;
  out[6] = packet.header.payloadLength;
  memcpy(out + Config::VOICE_HEADER_BYTES, packet.payload, sizeof(packet.payload));
  Detail::write32(out + Config::VOICE_PACKET_BYTES,
                  AudioDiagnostics::crc32(out, Config::VOICE_PACKET_BYTES));
  return true;
}

// Both outputs remain unchanged on rejection. Callers may only pass an accepted
// packet into reassembly; stale-message frames must not reset that transaction.
inline bool decodeData(const uint8_t* raw, size_t length, uint16_t expectedMessageId,
                       VoicePacket& packet, uint32_t& dataCrc) {
  if (raw == nullptr || length != DATA_BYTES) return false;
  VoicePacketHeader header = {};
  header.magic = raw[0];
  header.version = raw[1];
  header.messageId = Detail::read16(raw + 2);
  header.chunkIndex = raw[4];
  header.totalChunks = raw[5];
  header.payloadLength = raw[6];
  if (!isValidVoiceHeader(header) || header.messageId != expectedMessageId) return false;
  const uint32_t crc = Detail::read32(raw + Config::VOICE_PACKET_BYTES);
  if (crc != AudioDiagnostics::crc32(raw, Config::VOICE_PACKET_BYTES)) return false;
  packet.header = header;
  memcpy(packet.payload, raw + Config::VOICE_HEADER_BYTES, sizeof(packet.payload));
  dataCrc = crc;
  return true;
}

// The caller supplies ACK_BYTES writable bytes. Status zero means accepted;
// the echoed data CRC binds this ACK to the exact data frame being retried.
inline void encodeAck(uint16_t messageId, uint8_t index, uint32_t dataCrc,
                      uint8_t* out) {
  if (out == nullptr) return;
  out[0] = ACK_MAGIC;
  out[1] = ACK_VERSION;
  Detail::write16(out + 2, messageId);
  out[4] = index;
  out[5] = 0;
  Detail::write32(out + 6, dataCrc);
  Detail::write32(out + 10, AudioDiagnostics::crc32(out, 10));
}

inline bool decodeAck(const uint8_t* raw, size_t length, uint16_t expectedId,
                      uint8_t expectedIndex, uint32_t expectedDataCrc) {
  if (raw == nullptr || length != ACK_BYTES || expectedIndex >= Config::VOICE_TOTAL_CHUNKS) {
    return false;
  }
  return raw[0] == ACK_MAGIC && raw[1] == ACK_VERSION &&
         Detail::read16(raw + 2) == expectedId && raw[4] == expectedIndex &&
         raw[5] == 0 && Detail::read32(raw + 6) == expectedDataCrc &&
         Detail::read32(raw + 10) == AudioDiagnostics::crc32(raw, 10);
}

}  // namespace RadioFrame
