#pragma once

#include <stddef.h>
#include <stdint.h>

#include "config.h"
#include "protocol.h"

class VoiceChunker {
 public:
  VoiceChunker();

  // ---------------------------------------------------------------------------
  // TX side.
  // ---------------------------------------------------------------------------

  void beginTransmit(const uint8_t* audioBuffer, uint16_t messageId);

  bool makePacket(uint8_t chunkIndex, VoicePacket& outputPacket) const;

  // ---------------------------------------------------------------------------
  // RX side.
  // ---------------------------------------------------------------------------

  void beginReceive(uint16_t messageId);

  // Accept a complete raw VoicePacket received from simulated transport or LoRa.
  bool acceptPacket(const uint8_t* rawPacket, size_t rawPacketLength);

  void resetReceive();

  bool isReceiving() const;
  bool isComplete() const;
  bool hasReceivedAnyPackets() const;

  uint16_t activeMessageId() const;
  uint8_t receivedChunkCount() const;
  uint8_t missingChunkCount() const;

  const uint8_t* receiveBuffer() const;

 private:
  bool isChunkReceived(uint8_t chunkIndex) const;
  void markChunkReceived(uint8_t chunkIndex);

  // TX state.
  const uint8_t* txBuffer_;
  uint16_t txMessageId_;

  // RX state.
  uint8_t rxBuffer_[Config::AUDIO_BUFFER_BYTES];

  // 200 bits = 25 bytes.
  uint8_t receivedBitmap_[(Config::VOICE_TOTAL_CHUNKS + 7) / 8];

  uint16_t rxMessageId_;
  uint8_t rxReceivedChunks_;
  bool rxActive_;
};