#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "radio_frame.h"

static uint8_t pcm[Config::AUDIO_BUFFER_BYTES];
static VoiceChunker legacyTx;
static VoiceChunker receiver;
constexpr uint16_t MESSAGE_ID = 0x1234;

// Keep the tests' CRC field construction independent of the codec's LE helpers.
static void refreshCrc(uint8_t* raw, size_t bodyLength) {
  const uint32_t crc = AudioDiagnostics::crc32(raw, bodyLength);
  for (size_t i = 0; i < 4; ++i) raw[bodyLength + i] = (crc >> (i * 8)) & 0xFF;
}

static void rejectedData(const uint8_t* raw, size_t length,
                         uint16_t expectedId = MESSAGE_ID) {
  VoicePacket packet;
  memset(&packet, 0xA5, sizeof(packet));
  const VoicePacket before = packet;
  uint32_t crc = 0xDEADBEEF;
  assert(!RadioFrame::decodeData(raw, length, expectedId, packet, crc));
  assert(memcmp(&packet, &before, sizeof(packet)) == 0);
  assert(crc == 0xDEADBEEF);
}

static void testRoundtripAndLegacyCompatibility() {
  legacyTx.beginTransmit(pcm, MESSAGE_ID);
  receiver.beginReceive(MESSAGE_ID);
  // Reverse-order delivery exercises all payload offsets, including the last.
  for (int index = Config::VOICE_TOTAL_CHUNKS - 1; index >= 0; --index) {
    VoicePacket legacy, direct, decoded;
    assert(legacyTx.makePacket(index, legacy));
    assert(VoiceChunker::makePacketFromBuffer(pcm, MESSAGE_ID, index, direct));
    assert(memcmp(&legacy, &direct, sizeof(legacy)) == 0);
    uint8_t guarded[RadioFrame::DATA_BYTES + 2];
    memset(guarded, 0xA5, sizeof(guarded));
    uint8_t* frame = guarded + 1;
    assert(RadioFrame::encodeData(pcm, MESSAGE_ID, index, frame, RadioFrame::DATA_BYTES));
    assert(guarded[0] == 0xA5 && guarded[sizeof(guarded) - 1] == 0xA5);
    // The existing ESP32/host protocol already specifies this LE byte layout.
    assert(memcmp(frame, &legacy, sizeof(legacy)) == 0);
    assert(frame[2] == 0x34 && frame[3] == 0x12);
    uint32_t crc = 0;
    assert(RadioFrame::decodeData(frame, RadioFrame::DATA_BYTES, MESSAGE_ID, decoded, crc));
    assert(memcmp(&decoded, &legacy, sizeof(decoded)) == 0);
    assert(receiver.acceptPacket(reinterpret_cast<const uint8_t*>(&decoded), sizeof(decoded)));
    const uint8_t count = receiver.receivedChunkCount();
    assert(receiver.acceptPacket(reinterpret_cast<const uint8_t*>(&decoded), sizeof(decoded)));
    assert(receiver.receivedChunkCount() == count);
    uint8_t ack[RadioFrame::ACK_BYTES + 2];
    memset(ack, 0xA5, sizeof(ack));
    RadioFrame::encodeAck(MESSAGE_ID, index, crc, ack + 1);
    assert(ack[0] == 0xA5 && ack[sizeof(ack) - 1] == 0xA5);
    assert(RadioFrame::decodeAck(ack + 1, RadioFrame::ACK_BYTES, MESSAGE_ID, index, crc));
  }
  assert(receiver.isComplete() && receiver.activeMessageId() == MESSAGE_ID);
  assert(memcmp(pcm, receiver.receiveBuffer(), sizeof(pcm)) == 0);
}

static void testBoundsAndKnownWireBytes() {
  uint8_t frame[RadioFrame::DATA_BYTES + 1];
  uint8_t before[sizeof(frame)];
  memset(frame, 0xA5, sizeof(frame));
  memcpy(before, frame, sizeof(frame));
  for (size_t capacity = 0; capacity < RadioFrame::DATA_BYTES; ++capacity) {
    assert(!RadioFrame::encodeData(pcm, MESSAGE_ID, 0, frame, capacity));
    assert(memcmp(frame, before, sizeof(frame)) == 0);
  }
  assert(!RadioFrame::encodeData(nullptr, MESSAGE_ID, 0, frame, sizeof(frame)));
  assert(!RadioFrame::encodeData(pcm, MESSAGE_ID, 200, frame, sizeof(frame)));
  assert(!RadioFrame::encodeData(pcm, MESSAGE_ID, 255, frame, sizeof(frame)));
  assert(!RadioFrame::encodeData(pcm, MESSAGE_ID, 0, nullptr, RadioFrame::DATA_BYTES));
  assert(memcmp(frame, before, sizeof(frame)) == 0);

  VoicePacket packet;
  memset(&packet, 0x5A, sizeof(packet));
  const VoicePacket saved = packet;
  assert(!VoiceChunker::makePacketFromBuffer(nullptr, MESSAGE_ID, 0, packet));
  assert(!VoiceChunker::makePacketFromBuffer(pcm, MESSAGE_ID, 200, packet));
  assert(memcmp(&packet, &saved, sizeof(packet)) == 0);
  assert(RadioFrame::encodeData(pcm, MESSAGE_ID, 0, frame, sizeof(frame)));
  assert(frame[RadioFrame::DATA_BYTES] == 0xA5);
  uint32_t crc = 0;
  assert(RadioFrame::decodeData(frame, RadioFrame::DATA_BYTES, MESSAGE_ID, packet, crc));
  // Independent Python zlib.crc32 reference for this known header/payload.
  assert(crc == 0xD60AE26EU);
  const uint8_t crcBytes[] = {0x6E, 0xE2, 0x0A, 0xD6};
  assert(memcmp(frame + Config::VOICE_PACKET_BYTES, crcBytes, sizeof(crcBytes)) == 0);
  const uint8_t expectedAck[] = {
      0xFA, 0x01, 0x34, 0x12, 0x00, 0x00, 0x6E, 0xE2, 0x0A, 0xD6,
      0x90, 0xAB, 0x99, 0xE6};
  uint8_t ack[RadioFrame::ACK_BYTES];
  RadioFrame::encodeAck(MESSAGE_ID, 0, crc, ack);
  assert(sizeof(expectedAck) == sizeof(ack));
  assert(memcmp(ack, expectedAck, sizeof(ack)) == 0);
  RadioFrame::encodeAck(MESSAGE_ID, 0, crc, nullptr);  // Null output is a no-op.
  // Both ends of the full 16-bit message-ID range survive LE serialization.
  const uint16_t ids[] = {0, 0xFFFF};
  for (uint16_t id : ids) {
    assert(RadioFrame::encodeData(pcm, id, 199, frame, sizeof(frame)));
    assert(RadioFrame::decodeData(frame, RadioFrame::DATA_BYTES, id, packet, crc));
    assert(packet.header.messageId == id && packet.header.chunkIndex == 199);
    RadioFrame::encodeAck(id, 199, crc, ack);
    assert(RadioFrame::decodeAck(ack, sizeof(ack), id, 199, crc));
  }
}

static void testDataRejection() {
  uint8_t good[RadioFrame::DATA_BYTES];
  assert(RadioFrame::encodeData(pcm, MESSAGE_ID, 0, good, sizeof(good)));
  rejectedData(nullptr, sizeof(good));
  for (size_t length = 0; length < sizeof(good); ++length) rejectedData(good, length);
  uint8_t changed[RadioFrame::DATA_BYTES + 1];
  memcpy(changed, good, sizeof(good));
  changed[sizeof(good)] = 0;
  rejectedData(changed, sizeof(changed));
  rejectedData(good, sizeof(good), MESSAGE_ID + 1);
  // Every bit of every header, payload and CRC byte must be detected.
  for (size_t offset = 0; offset < sizeof(good); ++offset) {
    for (unsigned bit = 0; bit < 8; ++bit) {
      memcpy(changed, good, sizeof(good));
      changed[offset] ^= 1U << bit;
      rejectedData(changed, sizeof(good));
    }
  }
  // Valid CRCs must not bypass protocol or current-message checks.
  const uint8_t invalidHeader[] = {0, 2, 0x35, 0x13, 200, 199, 239};
  for (size_t offset = 0; offset < sizeof(invalidHeader); ++offset) {
    memcpy(changed, good, sizeof(good));
    changed[offset] = invalidHeader[offset];
    refreshCrc(changed, Config::VOICE_PACKET_BYTES);
    rejectedData(changed, sizeof(good));
  }
  for (unsigned length = 0; length < Config::VOICE_CHUNK_PAYLOAD_BYTES; ++length) {
    memcpy(changed, good, sizeof(good));
    changed[6] = length;
    refreshCrc(changed, Config::VOICE_PACKET_BYTES);
    rejectedData(changed, sizeof(good));
  }
  assert(RadioFrame::encodeData(pcm, MESSAGE_ID - 1, 199, changed, sizeof(changed)));
  rejectedData(changed, sizeof(good));
  // Rejected frames have not been handed to assembly or replaced its message.
  assert(receiver.activeMessageId() == MESSAGE_ID && receiver.isComplete());
  assert(memcmp(pcm, receiver.receiveBuffer(), sizeof(pcm)) == 0);
}

static void testAckRejection() {
  constexpr uint32_t dataCrc = 0xD60AE26E;
  constexpr uint8_t index = 17;
  uint8_t good[RadioFrame::ACK_BYTES];
  RadioFrame::encodeAck(MESSAGE_ID, index, dataCrc, good);
  assert(RadioFrame::decodeAck(good, sizeof(good), MESSAGE_ID, index, dataCrc));
  assert(!RadioFrame::decodeAck(nullptr, sizeof(good), MESSAGE_ID, index, dataCrc));
  for (size_t length = 0; length < sizeof(good); ++length) {
    assert(!RadioFrame::decodeAck(good, length, MESSAGE_ID, index, dataCrc));
  }
  uint8_t changed[RadioFrame::ACK_BYTES + 1];
  memcpy(changed, good, sizeof(good));
  changed[sizeof(good)] = 0;
  assert(!RadioFrame::decodeAck(changed, sizeof(changed), MESSAGE_ID, index, dataCrc));
  assert(!RadioFrame::decodeAck(good, sizeof(good), MESSAGE_ID + 1, index, dataCrc));
  assert(!RadioFrame::decodeAck(good, sizeof(good), MESSAGE_ID, index + 1, dataCrc));
  assert(!RadioFrame::decodeAck(good, sizeof(good), MESSAGE_ID, index, dataCrc ^ 1));
  for (size_t offset = 0; offset < sizeof(good); ++offset) {
    for (unsigned bit = 0; bit < 8; ++bit) {
      memcpy(changed, good, sizeof(good));
      changed[offset] ^= 1U << bit;
      assert(!RadioFrame::decodeAck(changed, sizeof(good), MESSAGE_ID, index, dataCrc));
    }
  }
  // Recomputed CRCs cannot authorize a wrong magic/version/message/index,
  // nonzero status or an ACK for a different data frame.
  for (size_t offset = 0; offset < 10; ++offset) {
    memcpy(changed, good, sizeof(good));
    changed[offset] ^= 1;
    refreshCrc(changed, 10);
    assert(!RadioFrame::decodeAck(changed, sizeof(good), MESSAGE_ID, index, dataCrc));
  }
  RadioFrame::encodeAck(MESSAGE_ID, 200, dataCrc, changed);
  assert(!RadioFrame::decodeAck(changed, RadioFrame::ACK_BYTES, MESSAGE_ID, 200, dataCrc));
  rejectedData(good, sizeof(good));  // ACKs cannot be mistaken for data frames.
}

int main() {
  for (size_t i = 0; i < sizeof(pcm); ++i) pcm[i] = (i * 37 + 11) & 255;
  testRoundtripAndLegacyCompatibility();
  testBoundsAndKnownWireBytes();
  testDataRejection();
  testAckRejection();
  puts("PASS: radio frame LE/CRC vectors, full reassembly, static TX compatibility, bounds, corruption and stale ACK rejection");
}
