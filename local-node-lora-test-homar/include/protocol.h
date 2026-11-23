#pragma once

#include <stddef.h>
#include <stdint.h>

#include "config.h"

#pragma pack(push, 1)

struct VoicePacketHeader {
  uint8_t magic;
  uint8_t version;
  uint16_t messageId;
  uint8_t chunkIndex;
  uint8_t totalChunks;
  uint8_t payloadLength;
};

struct VoicePacket {
  VoicePacketHeader header;
  uint8_t payload[Config::VOICE_CHUNK_PAYLOAD_BYTES];
};

#pragma pack(pop)

static_assert(sizeof(VoicePacketHeader) == Config::VOICE_HEADER_BYTES,
              "VoicePacketHeader must remain 7 bytes");

static_assert(sizeof(VoicePacket) == Config::VOICE_PACKET_BYTES,
              "VoicePacket must remain 247 bytes");

inline bool isValidVoiceHeader(const VoicePacketHeader& header) {
  return header.magic == Config::VOICE_PROTOCOL_MAGIC &&
         header.version == Config::VOICE_PROTOCOL_VERSION &&
         header.totalChunks == Config::VOICE_TOTAL_CHUNKS &&
         header.chunkIndex < Config::VOICE_TOTAL_CHUNKS &&
         // Version 1 has exactly 200 full chunks, including the final chunk.
         header.payloadLength == Config::VOICE_CHUNK_PAYLOAD_BYTES;
}
