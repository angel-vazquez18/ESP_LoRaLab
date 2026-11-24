#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "chunker.h"

// Match firmware storage discipline even on the host.
static VoiceChunker chunker;
static uint8_t pcm[Config::AUDIO_BUFFER_BYTES];

int main() {
  for (size_t i = 0; i < sizeof(pcm); ++i) pcm[i] = (i * 37 + 11) & 255;
  VoicePacket packet{};
  assert(!chunker.makePacket(0, packet));
  chunker.beginTransmit(pcm, 0x1234);
  assert(!chunker.makePacket(200, packet));
  for (int i = 199; i >= 0; --i) {
    assert(chunker.makePacket(i, packet));
    assert(chunker.acceptPacket(reinterpret_cast<uint8_t*>(&packet), sizeof(packet)));
  }
  assert(chunker.isComplete());
  assert(memcmp(pcm, chunker.receiveBuffer(), sizeof(pcm)) == 0);
  assert(chunker.makePacket(0, packet));
  const auto* raw = reinterpret_cast<const uint8_t*>(&packet);
  assert(raw[2] == 0x34 && raw[3] == 0x12);
  memset(packet.payload, 0, sizeof(packet.payload));
  assert(chunker.acceptPacket(raw, sizeof(packet)));
  assert(chunker.receivedChunkCount() == 200);
  assert(memcmp(pcm, chunker.receiveBuffer(), sizeof(pcm)) == 0);

  // Every malformed field and every truncated length must preserve RX state.
  assert(!chunker.acceptPacket(nullptr, sizeof(packet)));
  assert(chunker.makePacket(0, packet));
  for (size_t length = 0; length < sizeof(packet); ++length)
    assert(!chunker.acceptPacket(raw, length));
  uint8_t oversized[sizeof(packet) + 1] = {};
  memcpy(oversized, raw, sizeof(packet));
  assert(!chunker.acceptPacket(oversized, sizeof(oversized)));
  for (int field = 0; field < 5; ++field) {
    assert(chunker.makePacket(0, packet));
    packet.header.messageId = 0x5678;  // Rejection must not start a new message.
    switch (field) {
      case 0: packet.header.magic = 0; break;
      case 1: packet.header.version = 2; break;
      case 2: packet.header.totalChunks = 199; break;
      case 3: packet.header.chunkIndex = 200; break;
      case 4: packet.header.payloadLength = 241; break;
    }
    assert(!chunker.acceptPacket(raw, sizeof(packet)));
  }
  // Regression: self-consistent short/zero payloads formerly counted complete.
  for (unsigned length = 0; length < 240; ++length) {
    assert(chunker.makePacket(0, packet));
    packet.header.messageId = 0x5678;
    packet.header.payloadLength = length;
    assert(!chunker.acceptPacket(raw, sizeof(VoicePacketHeader) + length));
  }
  assert(chunker.activeMessageId() == 0x1234 && chunker.isComplete());
  assert(memcmp(pcm, chunker.receiveBuffer(), sizeof(pcm)) == 0);

  // New ID resets all old data. Deliberately lose first, last and spaced chunks.
  chunker.beginTransmit(pcm, 0x5678);
  unsigned received = 0;
  for (int i = 199; i >= 0; --i) {
    if (i == 0 || i == 199 || i % 17 == 0) continue;
    assert(chunker.makePacket(i, packet));
    assert(chunker.acceptPacket(raw, sizeof(packet)));
    ++received;
  }
  assert(chunker.activeMessageId() == 0x5678);
  assert(chunker.receivedChunkCount() == received);
  assert(chunker.missingChunkCount() == 200 - received);
  assert(!chunker.isComplete());
  for (size_t i = 0; i < sizeof(pcm); ++i) {
    const size_t index = i / 240;
    const bool missing = index == 0 || index == 199 || index % 17 == 0;
    assert(chunker.receiveBuffer()[i] == (missing ? 0 : pcm[i]));
  }
  chunker.resetReceive();
  assert(!chunker.isReceiving() && !chunker.hasReceivedAnyPackets());
  for (size_t i = 0; i < sizeof(pcm); ++i) assert(chunker.receiveBuffer()[i] == 0);
  puts("PASS: reverse order, duplicates, LE header, malformed/short packets, message reset, loss zero-fill");
}
