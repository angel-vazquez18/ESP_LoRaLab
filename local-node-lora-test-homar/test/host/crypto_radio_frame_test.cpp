#include <assert.h>
#include <stdio.h>
#include <string.h>
// The ESP32 AES HAL exports this macro; our public header must coexist with it.
#define TAG_BYTES (16)
#include "crypto_radio_frame.h"

int main() {
  uint8_t nonce[12], tag[16], frame[40], ack[14];
  for (unsigned i = 0; i < sizeof(nonce); ++i) nonce[i] = static_cast<uint8_t>(i);
  for (unsigned i = 0; i < sizeof(tag); ++i) tag[i] = static_cast<uint8_t>(0x80 + i);
  assert(CryptoRadioFrame::encodeMetadata(0x1234, nonce, tag, frame, sizeof(frame)));
  const uint8_t aad[] = {0xfb, 1, 0x34, 0x12, 0x80, 0xbb, 0, 0};
  assert(memcmp(frame, aad, sizeof(aad)) == 0);
  assert(memcmp(frame + 8, nonce, 12) == 0);
  assert(memcmp(frame + 20, tag, 16) == 0);
  assert(CryptoRadioFrame::validMetadata(frame, 40, 0x1234));
  assert(!CryptoRadioFrame::validMetadata(frame, 39, 0x1234));
  assert(!CryptoRadioFrame::validMetadata(frame, 40, 0x1235));
  assert(!CryptoRadioFrame::validMetadata(nullptr, 40, 0x1234));
  assert(!CryptoRadioFrame::encodeMetadata(0, nonce, tag, frame, 40));
  assert(!CryptoRadioFrame::encodeMetadata(1, nonce, tag, frame, 39));
  for (unsigned position = 0; position < sizeof(frame); ++position) {
    frame[position] ^= 1;
    assert(!CryptoRadioFrame::validMetadata(frame, 40, 0x1234));
    frame[position] ^= 1;
  }
  const uint32_t crc = CryptoRadioFrame::metadataCrc(frame);
  RadioFrame::encodeAck(0x1234, 255, crc, ack);
  assert(CryptoRadioFrame::decodeMetadataAck(ack, 14, 0x1234, crc));
  assert(!RadioFrame::decodeAck(ack, 14, 0x1234, 0, crc));
  assert(!CryptoRadioFrame::decodeMetadataAck(ack, 14, 0x1235, crc));
  assert(!CryptoRadioFrame::decodeMetadataAck(ack, 14, 0x1234, crc ^ 1));
  assert(!CryptoRadioFrame::decodeMetadataAck(ack, 13, 0x1234, crc));
  RadioFrame::encodeAck(0x1234, 0, crc, ack);
  assert(!CryptoRadioFrame::decodeMetadataAck(ack, 14, 0x1234, crc));
  frame[4] ^= 1; // Even with a repaired CRC, the wrong length is rejected.
  RadioFrame::Detail::write32(frame + 36, AudioDiagnostics::crc32(frame, 36));
  assert(!CryptoRadioFrame::validMetadata(frame, 40, 0x1234));
  puts("PASS: crypto metadata layout, bit corruption, length/id validation, ACK binding");
}
