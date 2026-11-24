#include "chunker.h"

#include <string.h>

VoiceChunker::VoiceChunker()
    : txBuffer_(nullptr),
      txMessageId_(0),
      rxMessageId_(0),
      rxReceivedChunks_(0),
      rxActive_(false) {
  resetReceive();
}

void VoiceChunker::beginTransmit(const uint8_t* audioBuffer,
                                 uint16_t messageId) {
  txBuffer_ = audioBuffer;
  txMessageId_ = messageId;
}

bool VoiceChunker::makePacket(uint8_t chunkIndex,
                              VoicePacket& outputPacket) const {
  if (txBuffer_ == nullptr) {
    return false;
  }

  if (chunkIndex >= Config::VOICE_TOTAL_CHUNKS) {
    return false;
  }

  const size_t audioOffset =
      static_cast<size_t>(chunkIndex) *
      Config::VOICE_CHUNK_PAYLOAD_BYTES;

  outputPacket.header.magic = Config::VOICE_PROTOCOL_MAGIC;
  outputPacket.header.version = Config::VOICE_PROTOCOL_VERSION;
  outputPacket.header.messageId = txMessageId_;
  outputPacket.header.chunkIndex = chunkIndex;
  outputPacket.header.totalChunks = Config::VOICE_TOTAL_CHUNKS;
  outputPacket.header.payloadLength = Config::VOICE_CHUNK_PAYLOAD_BYTES;

  memcpy(outputPacket.payload,
         txBuffer_ + audioOffset,
         Config::VOICE_CHUNK_PAYLOAD_BYTES);

  return true;
}

void VoiceChunker::beginReceive(uint16_t messageId) {
  // This is critical to loss handling.
  //
  // Any chunk that never arrives remains zero PCM, which becomes silence
  // during speaker playback.
  memset(rxBuffer_, 0, sizeof(rxBuffer_));
  memset(receivedBitmap_, 0, sizeof(receivedBitmap_));

  rxMessageId_ = messageId;
  rxReceivedChunks_ = 0;
  rxActive_ = true;
}

bool VoiceChunker::acceptPacket(const uint8_t* rawPacket,
                                size_t rawPacketLength) {
  if (rawPacket == nullptr) {
    return false;
  }

  if (rawPacketLength < sizeof(VoicePacketHeader)) {
    return false;
  }

  VoicePacketHeader header;
  memcpy(&header, rawPacket, sizeof(header));

  if (!isValidVoiceHeader(header)) {
    return false;
  }

  const size_t expectedPacketLength =
      sizeof(VoicePacketHeader) + header.payloadLength;

  if (rawPacketLength != expectedPacketLength) {
    return false;
  }

  // A packet from a new message starts a fresh assembly transaction.
  if (!rxActive_ || header.messageId != rxMessageId_) {
    beginReceive(header.messageId);
  }

  const uint8_t chunkIndex = header.chunkIndex;

  const size_t destinationOffset =
      static_cast<size_t>(chunkIndex) *
      Config::VOICE_CHUNK_PAYLOAD_BYTES;

  if (destinationOffset + header.payloadLength > sizeof(rxBuffer_)) {
    return false;
  }

  // Ignore duplicate packet payloads but report them as valid protocol data.
  if (isChunkReceived(chunkIndex)) {
    return true;
  }

  memcpy(rxBuffer_ + destinationOffset,
         rawPacket + sizeof(VoicePacketHeader),
         header.payloadLength);

  markChunkReceived(chunkIndex);
  ++rxReceivedChunks_;

  return true;
}

void VoiceChunker::resetReceive() {
  memset(rxBuffer_, 0, sizeof(rxBuffer_));
  memset(receivedBitmap_, 0, sizeof(receivedBitmap_));

  rxMessageId_ = 0;
  rxReceivedChunks_ = 0;
  rxActive_ = false;
}

bool VoiceChunker::isReceiving() const {
  return rxActive_;
}

bool VoiceChunker::isComplete() const {
  return rxActive_ &&
         rxReceivedChunks_ == Config::VOICE_TOTAL_CHUNKS;
}

bool VoiceChunker::hasReceivedAnyPackets() const {
  return rxReceivedChunks_ > 0;
}

uint16_t VoiceChunker::activeMessageId() const {
  return rxMessageId_;
}

uint8_t VoiceChunker::receivedChunkCount() const {
  return rxReceivedChunks_;
}

uint8_t VoiceChunker::missingChunkCount() const {
  return Config::VOICE_TOTAL_CHUNKS - rxReceivedChunks_;
}

const uint8_t* VoiceChunker::receiveBuffer() const {
  return rxBuffer_;
}

bool VoiceChunker::isChunkReceived(uint8_t chunkIndex) const {
  const uint8_t byteIndex = chunkIndex / 8;
  const uint8_t bitIndex = chunkIndex % 8;

  return (receivedBitmap_[byteIndex] & (1U << bitIndex)) != 0;
}

void VoiceChunker::markChunkReceived(uint8_t chunkIndex) {
  const uint8_t byteIndex = chunkIndex / 8;
  const uint8_t bitIndex = chunkIndex % 8;

  receivedBitmap_[byteIndex] |= (1U << bitIndex);
}