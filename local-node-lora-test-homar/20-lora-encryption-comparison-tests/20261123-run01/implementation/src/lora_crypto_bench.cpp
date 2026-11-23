// Separate, explicitly selected RF integrity firmware. No audio driver runs here.
#if defined(LORA_INTEGRITY_BENCH) && LORA_INTEGRITY_BENCH
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <esp_heap_caps.h>
#include <esp_mac.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <new>
#include <string.h>
#include <mbedtls/gcm.h>
#include <mbedtls/platform_util.h>
#include "chunker.h"
#include "radio_frame.h"
#include "crypto_radio_frame.h"
#include "audio_diagnostics.h"
#include "lora_bench_display.h"

namespace {
constexpr char FIRMWARE[] = "lora-crypto-1-gcm";
#if LORA_BENCH_NODE_ID == 6
constexpr char NODE_LABEL[] = "Heltec-A / COM6";
#else
constexpr char NODE_LABEL[] = "Heltec-B / COM7";
#endif
using DisplayState = LoraBenchDisplay::State;
constexpr float FREQUENCY_MHZ = 915.0f;
constexpr float BANDWIDTH_KHZ = 500.0f;
constexpr uint8_t SPREADING_FACTOR = 7;
constexpr uint8_t CODING_RATE = 5;
constexpr int8_t CHIP_POWER_DBM = -9;
constexpr uint32_t ACK_TIMEOUT_MS = 500;
constexpr unsigned MAX_ATTEMPTS = 6;
constexpr uint32_t ACK_TURNAROUND_MS = 8;

class HeltecRadio : public SX1262 {
 public:
  explicit HeltecRadio(Module* module) : SX1262(module) {}
  int16_t applyReceivePatch() {
    uint8_t value = 0;
    int16_t result = readRegister(0x08b5, &value, 1);
    if (result != RADIOLIB_ERR_NONE) return result;
    value |= 0x01;
    return writeRegister(0x08b5, &value, 1);
  }
};
Module radioModule(8, 14, 12, 13, SPI);
HeltecRadio radio(&radioModule);
enum class Role { None, Tx, Rx };
Role role = Role::None;
bool gcmMode = false, keyReady = false, nonceReady = false;
bool sealed = false, metadataReceived = false, authenticated = false, decryptAttempted = false;
mbedtls_gcm_context cryptoContext;
uint8_t cryptoKey[16] = {}, nonce[12] = {}, tag[16] = {}, metadata[CryptoRadioFrame::META_BYTES] = {};
uint8_t* cryptoBuffer = nullptr;
size_t cryptoAllocationActual = 0;
int32_t cryptoLibraryHeapDelta = 0;
uint64_t keySetupUs = 0, encryptionUs = 0, decryptionUs = 0, messageReadyUs = 0;
uint64_t firstTransportRxUs = 0;
uint32_t authFailures = 0;
bool radioReady = false, armed = false, transmitting = false, cancelled = false;
bool loaded = false, completeReported = false;
int16_t radioInitStatus = -1;
uint8_t* txPcm = nullptr;
VoiceChunker* receiver = nullptr;
size_t allocationRequested = 0, allocationActual = 0;
uint32_t psramBefore = 0, internalBefore = 0;
char deviceMac[18] = {}, bootId[40] = {};
uint16_t messageId = 0;
uint32_t duplicates = 0, crcErrors = 0, appErrors = 0;
uint32_t rxPackets = 0, ackPackets = 0;
uint64_t firstRxUs = 0, lastRxUs = 0;
volatile bool dioFlag = false;
volatile uint64_t dioTimeUs = 0;
uint8_t rfTx[RadioFrame::DATA_BYTES] = {};
uint8_t rfRx[255] = {};
uint8_t ackFrame[RadioFrame::ACK_BYTES] = {};
VoicePacket decodedPacket{};
char command[128] = {};
size_t commandLength = 0;
bool discardCommand = false;
uint32_t txRunsStarted = 0, rfTxCallsTotal = 0;
// Schema 1: local elapsed processing time, including timer/scheduling overhead.
// No OLED, radio I/O, ACK waits or serial logging lies inside these intervals.
uint64_t chunkingTotalUs = 0, dechunkingTotalUs = 0, dechunkingDuplicateTotalUs = 0;
uint32_t chunkingCount = 0, dechunkingCount = 0, dechunkingDuplicateCount = 0;

uint64_t nowUs() { return static_cast<uint64_t>(esp_timer_get_time()); }
const char* roleName() { return role == Role::Tx ? "TX" : role == Role::Rx ? "RX" : "NONE"; }
const char* modeName() { return gcmMode ? "GCM" : "PLAIN"; }

void printHex(const uint8_t* data, size_t size) {
  for (size_t i = 0; i < size; ++i) Serial.printf("%02x", data[i]);
}

bool parseHex(const char* text, uint8_t* out, size_t bytes) {
  if (strlen(text) != bytes * 2) return false;
  for (size_t i = 0; i < bytes * 2; ++i) {
    const char c = text[i];
    const int v = c >= '0' && c <= '9' ? c - '0' :
                  c >= 'a' && c <= 'f' ? c - 'a' + 10 :
                  c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
    if (v < 0) return false;
    if (!(i & 1)) out[i / 2] = static_cast<uint8_t>(v << 4);
    else out[i / 2] |= static_cast<uint8_t>(v);
  }
  return true;
}

void resetCryptoMessage() {
  nonceReady = sealed = metadataReceived = authenticated = decryptAttempted = false;
  encryptionUs = decryptionUs = messageReadyUs = firstTransportRxUs = 0;
  authFailures = 0;
  memset(nonce, 0, sizeof(nonce));
  memset(tag, 0, sizeof(tag));
  memset(metadata, 0, sizeof(metadata));
}

void printCryptoFields() {
  Serial.printf(
      ",\"mode\":\"%s\",\"crypto_schema\":1,\"crypto_algorithm\":\"AES-128-GCM\","
      "\"key_ready\":%s,\"authenticated\":%s,\"auth_failures\":%lu,"
      "\"encryption_us\":%llu,\"decryption_us\":%llu,\"key_setup_us\":%llu,"
      "\"message_ready_us\":%llu,\"first_transport_rx_us\":%llu,"
      "\"nonce_bytes\":12,\"tag_bytes\":16,\"crypto_buffer_requested_bytes\":%u,"
      "\"crypto_buffer_actual_bytes\":%u,\"crypto_context_bytes\":%u,"
      "\"crypto_key_bytes\":16,\"crypto_metadata_bytes\":%u,"
      "\"crypto_library_heap_delta_bytes\":%ld",
      modeName(), keyReady ? "true" : "false", authenticated ? "true" : "false",
      static_cast<unsigned long>(authFailures), encryptionUs, decryptionUs, keySetupUs,
      messageReadyUs, firstTransportRxUs,
      cryptoBuffer ? static_cast<unsigned>(Config::AUDIO_BUFFER_BYTES) : 0U,
      static_cast<unsigned>(cryptoAllocationActual), static_cast<unsigned>(sizeof(cryptoContext)),
      static_cast<unsigned>(sizeof(metadata)), static_cast<long>(cryptoLibraryHeapDelta));
}

void ARDUINO_ISR_ATTR onDio1() {
  dioTimeUs = static_cast<uint64_t>(esp_timer_get_time());
  dioFlag = true;
}

void clearIrqFlag() {
  noInterrupts();
  dioFlag = false;
  dioTimeUs = 0;
  interrupts();
}

bool takeIrq(uint64_t& stamp) {
  noInterrupts();
  const bool present = dioFlag;
  stamp = dioTimeUs;
  dioFlag = false;
  interrupts();
  return present;
}

void error(const char* reason) {
  Serial.printf("{\"event\":\"error\",\"reason\":\"%s\",\"time_us\":%llu}\n", reason, nowUs());
}

void printMemoryFields() {
  Serial.printf(
      ",\"payload_capacity_bytes\":%u,\"allocation_requested_bytes\":%u,"
      "\"allocation_actual_bytes\":%u,\"allocation_storage\":\"PSRAM\","
      "\"chunker_object_bytes\":%u,\"chunker_bitmap_bytes\":%u,"
      "\"packet_scratch_bytes\":%u,\"internal_heap_before_bytes\":%lu,"
      "\"internal_heap_free_bytes\":%lu,\"internal_heap_min_free_bytes\":%lu,"
      "\"psram_before_bytes\":%lu,\"psram_free_bytes\":%lu,\"psram_total_bytes\":%lu,"
      "\"flash_total_bytes\":%lu",
      role == Role::None ? 0U : static_cast<unsigned>(Config::AUDIO_BUFFER_BYTES),
      static_cast<unsigned>(allocationRequested), static_cast<unsigned>(allocationActual),
      role == Role::Rx ? static_cast<unsigned>(sizeof(VoiceChunker)) : 0U,
      role == Role::Rx ? 25U : 0U,
      static_cast<unsigned>(sizeof(rfTx) + sizeof(rfRx) + sizeof(ackFrame) + sizeof(decodedPacket)),
      static_cast<unsigned long>(internalBefore), static_cast<unsigned long>(ESP.getFreeHeap()),
      static_cast<unsigned long>(ESP.getMinFreeHeap()), static_cast<unsigned long>(psramBefore),
      static_cast<unsigned long>(ESP.getFreePsram()), static_cast<unsigned long>(ESP.getPsramSize()),
      static_cast<unsigned long>(ESP.getFlashChipSize()));
  printCryptoFields();
}

void printDisplayFields() {
  Serial.printf(
      ",\"node_label\":\"%s\",\"oled_ready\":%s,\"oled_layout_ok\":%s,"
      "\"state\":\"%s\",\"test_current\":%u,\"test_total\":%u,"
      "\"transmitting\":%s,\"tx_runs_started\":%lu,\"rf_tx_calls_total\":%lu",
      NODE_LABEL, LoraBenchDisplay::ready() ? "true" : "false",
      LoraBenchDisplay::layoutOk() ? "true" : "false",
      LoraBenchDisplay::stateName(LoraBenchDisplay::state()),
      LoraBenchDisplay::currentTest(), LoraBenchDisplay::totalTests(),
      transmitting ? "true" : "false", static_cast<unsigned long>(txRunsStarted),
      static_cast<unsigned long>(rfTxCallsTotal));
}

void resetProcessingTimings() {
  chunkingTotalUs = dechunkingTotalUs = dechunkingDuplicateTotalUs = 0;
  chunkingCount = dechunkingCount = dechunkingDuplicateCount = 0;
}

void printTimingFields() {
  Serial.printf(
      ",\"timing_schema\":1,\"chunking_total_us\":%llu,\"chunking_count\":%lu,"
      "\"dechunking_total_us\":%llu,\"dechunking_count\":%lu,"
      "\"dechunking_duplicate_total_us\":%llu,\"dechunking_duplicate_count\":%lu",
      chunkingTotalUs, static_cast<unsigned long>(chunkingCount),
      dechunkingTotalUs, static_cast<unsigned long>(dechunkingCount),
      dechunkingDuplicateTotalUs, static_cast<unsigned long>(dechunkingDuplicateCount));
}

void hello() {
  Serial.printf(
      "{\"event\":\"hello\",\"firmware\":\"%s\",\"mac\":\"%s\",\"boot_id\":\"%s\","
      "\"node\":%d,\"role\":\"%s\",\"radio_ready\":%s,\"radio_init_status\":%d,"
      "\"frequency_mhz\":%.1f,\"bw_khz\":%.1f,\"sf\":%u,\"cr\":%u,\"sync_word\":18,"
      "\"chip_power_dbm\":%d,\"fem_rx_mode\":\"bypass\",\"tcxo_volts\":1.8,"
      "\"data_packet_bytes\":%u,\"ack_packet_bytes\":%u,\"data_airtime_us\":%lu,"
      "\"ack_airtime_us\":%lu,\"ack_timeout_ms\":%lu,\"max_attempts\":%u,"
      "\"sample_rate_hz\":8000,\"bits\":16,\"channels\":1,\"time_us\":%llu",
      FIRMWARE, deviceMac, bootId, LORA_BENCH_NODE_ID, roleName(), radioReady ? "true" : "false",
      radioInitStatus, FREQUENCY_MHZ, BANDWIDTH_KHZ, SPREADING_FACTOR, CODING_RATE, CHIP_POWER_DBM,
      static_cast<unsigned>(RadioFrame::DATA_BYTES), static_cast<unsigned>(RadioFrame::ACK_BYTES),
      radioReady ? static_cast<unsigned long>(radio.getTimeOnAir(RadioFrame::DATA_BYTES)) : 0UL,
      radioReady ? static_cast<unsigned long>(radio.getTimeOnAir(RadioFrame::ACK_BYTES)) : 0UL,
      static_cast<unsigned long>(ACK_TIMEOUT_MS), MAX_ATTEMPTS, nowUs());
  printMemoryFields();
  printDisplayFields();
  printTimingFields();
  Serial.printf(",\"metadata_packet_bytes\":%u,\"metadata_airtime_us\":%lu",
                static_cast<unsigned>(CryptoRadioFrame::META_BYTES),
                radioReady ? static_cast<unsigned long>(radio.getTimeOnAir(CryptoRadioFrame::META_BYTES)) : 0UL);
  Serial.println("}");
}

int16_t startReceive() {
  clearIrqFlag();
  return radio.startReceive();
}

void resumeReceiver() {
  if (startReceive() != RADIOLIB_ERR_NONE) {
    armed = false;
    LoraBenchDisplay::setState(DisplayState::Idle);
    error("receive_restart_failed");
  } else LoraBenchDisplay::setState(DisplayState::Receiving);
}

void status() {
  Serial.printf(
      "{\"event\":\"status\",\"role\":\"%s\",\"id\":%u,\"armed\":%s,"
      "\"loaded\":%s,\"received_chunks\":%u,\"duplicates\":%lu,\"crc_errors\":%lu,"
      "\"app_errors\":%lu,\"rx_packets\":%lu,\"ack_packets\":%lu,"
      "\"first_rx_us\":%llu,\"last_rx_us\":%llu,\"time_us\":%llu",
      roleName(), messageId, armed ? "true" : "false", loaded ? "true" : "false",
      receiver ? receiver->receivedChunkCount() : 0U,
      static_cast<unsigned long>(duplicates), static_cast<unsigned long>(crcErrors),
      static_cast<unsigned long>(appErrors), static_cast<unsigned long>(rxPackets),
      static_cast<unsigned long>(ackPackets), firstRxUs, lastRxUs, nowUs());
  printMemoryFields();
  printDisplayFields();
  printTimingFields();
  Serial.println("}");
}

void setRole(Role next) {
  if (!radioReady) { error("radio_not_ready"); return; }
  radio.standby();
  armed = loaded = completeReported = false;
  resetProcessingTimings();
  resetCryptoMessage();
  LoraBenchDisplay::setState(DisplayState::Idle);
  messageId = 0;
  if (txPcm) { heap_caps_free(txPcm); txPcm = nullptr; }
  if (receiver) { receiver->~VoiceChunker(); heap_caps_free(receiver); receiver = nullptr; }
  if (cryptoBuffer) { mbedtls_platform_zeroize(cryptoBuffer, Config::AUDIO_BUFFER_BYTES); heap_caps_free(cryptoBuffer); cryptoBuffer = nullptr; }
  cryptoAllocationActual = 0;
  role = Role::None;
  allocationRequested = allocationActual = 0;
  internalBefore = ESP.getFreeHeap();
  psramBefore = ESP.getFreePsram();
  const size_t bytes = next == Role::Tx ? Config::AUDIO_BUFFER_BYTES : sizeof(VoiceChunker);
  void* storage = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!storage) { error("psram_allocation_failed"); return; }
  allocationRequested = bytes;
  allocationActual = heap_caps_get_allocated_size(storage);
  if (next == Role::Tx) { txPcm = static_cast<uint8_t*>(storage); memset(txPcm, 0, bytes); }
  else receiver = new (storage) VoiceChunker();
  if (gcmMode) {
    cryptoBuffer = static_cast<uint8_t*>(heap_caps_malloc(Config::AUDIO_BUFFER_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!cryptoBuffer) {
      if (txPcm) { heap_caps_free(txPcm); txPcm = nullptr; }
      if (receiver) { receiver->~VoiceChunker(); heap_caps_free(receiver); receiver = nullptr; }
      allocationRequested = allocationActual = 0;
      error("crypto_psram_allocation_failed"); return;
    }
    cryptoAllocationActual = heap_caps_get_allocated_size(cryptoBuffer);
    memset(cryptoBuffer, 0, Config::AUDIO_BUFFER_BYTES);
  }
  role = next;
  LoraBenchDisplay::setRole(role == Role::Tx);
  Serial.printf("{\"event\":\"role\",\"role\":\"%s\",\"time_us\":%llu", roleName(), nowUs());
  printMemoryFields();
  Serial.println("}");
}

void loadPcm(uint32_t expectedCrc) {
  if (role != Role::Tx || !txPcm) { error("load_requires_tx_role"); return; }
  loaded = false;
  sealed = false;
  constexpr size_t USB_BLOCK_BYTES = 512;
  Serial.printf("{\"event\":\"load_ready\",\"bytes\":%u,\"block_bytes\":%u}\n",
                static_cast<unsigned>(Config::AUDIO_BUFFER_BYTES), static_cast<unsigned>(USB_BLOCK_BYTES));
  size_t received = 0;
  size_t nextBoundary = USB_BLOCK_BYTES;
  const uint64_t deadline = nowUs() + 20000000ULL;
  while (received < Config::AUDIO_BUFFER_BYTES && nowUs() < deadline) {
    const int available = Serial.available();
    if (available > 0) {
      const size_t wanted = min(static_cast<size_t>(available), nextBoundary - received);
      received += Serial.readBytes(txPcm + received, wanted);
      if (received == nextBoundary) {
        Serial.printf("{\"event\":\"load_block\",\"received\":%u}\n", static_cast<unsigned>(received));
        nextBoundary = min(received + USB_BLOCK_BYTES, static_cast<size_t>(Config::AUDIO_BUFFER_BYTES));
      }
    } else delay(1);
  }
  if (received != Config::AUDIO_BUFFER_BYTES) { error("load_timeout"); return; }
  const uint32_t crc = AudioDiagnostics::crc32(txPcm, Config::AUDIO_BUFFER_BYTES);
  if (crc != expectedCrc) { error("load_crc_mismatch"); return; }
  loaded = true;
  Serial.printf("{\"event\":\"loaded\",\"bytes\":%u,\"crc32\":\"%08lx\",\"time_us\":%llu}\n",
                static_cast<unsigned>(received), static_cast<unsigned long>(crc), nowUs());
}

void dump(bool tx) {
  if ((tx && (role != Role::Tx || !loaded)) || (!tx && (role != Role::Rx || !receiver))) {
    error("dump_role_or_buffer_unavailable"); return;
  }
  // Host requests export after TX completion. No radio data enters through USB.
  radio.standby();
  armed = false;
  LoraBenchDisplay::setState(DisplayState::Idle);
  if (!tx && gcmMode && !authenticated) { error("dump_rx_requires_authentication"); return; }
  const uint8_t* data = tx ? txPcm : gcmMode ? cryptoBuffer : receiver->receiveBuffer();
  const uint32_t crc = AudioDiagnostics::crc32(data, Config::AUDIO_BUFFER_BYTES);
  Serial.printf("{\"event\":\"dump_begin\",\"role\":\"%s\",\"bytes\":%u,"
                "\"crc32\":\"%08lx\",\"complete\":%s,\"time_us\":%llu}\n",
                tx ? "TX" : "RX", static_cast<unsigned>(Config::AUDIO_BUFFER_BYTES),
                static_cast<unsigned long>(crc), (tx || receiver->isComplete()) ? "true" : "false", nowUs());
  size_t written = 0;
  const uint64_t deadline = nowUs() + 20000000ULL;
  while (written < Config::AUDIO_BUFFER_BYTES && nowUs() < deadline) {
    const size_t block = min(static_cast<size_t>(512), Config::AUDIO_BUFFER_BYTES - written);
    written += Serial.write(data + written, block);
    delay(1);
  }
  Serial.printf("\n{\"event\":\"dump_end\",\"role\":\"%s\",\"bytes\":%u}\n",
                tx ? "TX" : "RX", static_cast<unsigned>(written));
}

void dumpCipher() {
  const uint8_t* data = role == Role::Tx ? cryptoBuffer : receiver ? receiver->receiveBuffer() : nullptr;
  const bool complete = role == Role::Tx ? sealed : receiver && receiver->isComplete();
  if (!gcmMode || !data || !complete) { error("ciphertext_unavailable"); return; }
  radio.standby(); armed = false;
  const uint32_t crc = AudioDiagnostics::crc32(data, Config::AUDIO_BUFFER_BYTES);
  Serial.printf("{\"event\":\"dump_begin\",\"role\":\"CIPHER\",\"bytes\":48000,\"complete\":true,\"crc32\":\"%08lx\",\"time_us\":%llu}\n",
                static_cast<unsigned long>(crc), nowUs());
  size_t written = 0;
  const uint64_t deadline = nowUs() + 20000000ULL;
  while (written < Config::AUDIO_BUFFER_BYTES && nowUs() < deadline) {
    const size_t block = min(static_cast<size_t>(512), Config::AUDIO_BUFFER_BYTES - written);
    written += Serial.write(data + written, block);
    delay(1);
  }
  Serial.printf("\n{\"event\":\"dump_end\",\"role\":\"CIPHER\",\"bytes\":%u}\n", static_cast<unsigned>(written));
}

bool sealMessage(uint16_t id) {
  if (!keyReady || !nonceReady || !cryptoBuffer) { error("encryption_not_ready"); return false; }
  nonceReady = false;  // One encryption per provisioned nonce; retries reuse ciphertext.
  sealed = false;
  CryptoRadioFrame::encodeAad(id, metadata);
  const uint64_t start = nowUs();
  const int result = mbedtls_gcm_crypt_and_tag(&cryptoContext, MBEDTLS_GCM_ENCRYPT,
      Config::AUDIO_BUFFER_BYTES, nonce, sizeof(nonce), metadata, CryptoRadioFrame::AAD_BYTES,
      txPcm, cryptoBuffer, sizeof(tag), tag);
  encryptionUs = nowUs() - start;
  if (result != 0) { mbedtls_platform_zeroize(cryptoBuffer, Config::AUDIO_BUFFER_BYTES); error("gcm_encryption_failed"); return false; }
  sealed = CryptoRadioFrame::encodeMetadata(id, nonce, tag, metadata, sizeof(metadata));
  Serial.printf("{\"event\":\"encrypted\",\"id\":%u,\"encryption_us\":%llu,\"nonce_hex\":\"", id, encryptionUs);
  printHex(nonce, sizeof(nonce)); Serial.print("\",\"tag_hex\":\""); printHex(tag, sizeof(tag));
  Serial.print("\",\"metadata_hex\":\""); printHex(metadata, sizeof(metadata));
  Serial.println("\"}");
  return sealed;
}

bool authenticateMessage() {
  if (decryptAttempted) return authenticated;
  decryptAttempted = true;
  const uint64_t start = nowUs();
  const int result = mbedtls_gcm_auth_decrypt(&cryptoContext, Config::AUDIO_BUFFER_BYTES,
      metadata + CryptoRadioFrame::NONCE_OFFSET, CryptoRadioFrame::NONCE_BYTES,
      metadata, CryptoRadioFrame::AAD_BYTES, metadata + CryptoRadioFrame::TAG_OFFSET,
      CryptoRadioFrame::GCM_TAG_BYTES, receiver->receiveBuffer(), cryptoBuffer);
  decryptionUs = nowUs() - start;
  authenticated = result == 0;
  if (!authenticated) {
    ++authFailures;
    mbedtls_platform_zeroize(cryptoBuffer, Config::AUDIO_BUFFER_BYTES);
  } else messageReadyUs = nowUs();
  Serial.printf("{\"event\":\"decrypted\",\"id\":%u,\"decryption_us\":%llu,\"authenticated\":%s,"
                "\"message_ready_us\":%llu}\n", messageId, decryptionUs,
                authenticated ? "true" : "false",
                messageReadyUs);
  return authenticated;
}

void receiveMetadata(uint64_t arrival, size_t length) {
  if (!gcmMode || !keyReady || !cryptoBuffer || !CryptoRadioFrame::validMetadata(rfRx, length, messageId)) {
    ++appErrors; error("invalid_crypto_metadata"); resumeReceiver(); return;
  }
  const bool duplicate = metadataReceived;
  if (duplicate && memcmp(metadata, rfRx, sizeof(metadata)) != 0) {
    ++appErrors; error("conflicting_crypto_metadata"); resumeReceiver(); return;
  }
  if (!duplicate) {
    memcpy(metadata, rfRx, sizeof(metadata));
    metadataReceived = true;
    firstTransportRxUs = arrival;
  }
  const uint32_t crc = CryptoRadioFrame::metadataCrc(metadata);
  RadioFrame::encodeAck(messageId, CryptoRadioFrame::META_ACK_INDEX, crc, ackFrame);
  delay(ACK_TURNAROUND_MS);
  ++rfTxCallsTotal;
  const int16_t ackStatus = radio.transmit(ackFrame, sizeof(ackFrame));
  const int16_t resumeStatus = startReceive();
  Serial.printf("{\"event\":\"rx_metadata\",\"id\":%u,\"rx_us\":%llu,\"duplicate\":%s,"
                "\"ack_status\":%d,\"metadata_crc32\":\"%08lx\",\"metadata_hex\":\"",
                messageId, arrival, duplicate ? "true" : "false", ackStatus, static_cast<unsigned long>(crc));
  printHex(metadata, sizeof(metadata)); Serial.println("\"}");
  if (resumeStatus != RADIOLIB_ERR_NONE) { armed = false; error("receive_restart_failed"); }
  LoraBenchDisplay::setState(armed ? DisplayState::Receiving : DisplayState::Idle);
}

void receivePacket() {
  uint64_t arrival = 0;
  if (!takeIrq(arrival)) return;
  const size_t length = radio.getPacketLength();
  int16_t result = length <= sizeof(rfRx) ? radio.readData(rfRx, length) : -9001;
  const float rssi = radio.getRSSI();
  const float snr = radio.getSNR();
  if (result != RADIOLIB_ERR_NONE) {
    if (result == RADIOLIB_ERR_CRC_MISMATCH) ++crcErrors;
    else ++appErrors;
    Serial.printf("{\"event\":\"rx_error\",\"status\":%d,\"time_us\":%llu}\n", result, arrival);
    resumeReceiver();
    return;
  }
  if (length == CryptoRadioFrame::META_BYTES || (length > 0 && rfRx[0] == CryptoRadioFrame::META_MAGIC)) {
    receiveMetadata(arrival, length); return;
  }
  if (gcmMode && (!metadataReceived || !keyReady || !cryptoBuffer)) {
    ++appErrors; error("data_requires_crypto_metadata"); resumeReceiver(); return;
  }
  uint32_t dataCrc = 0;
  LoraBenchDisplay::setState(DisplayState::Dechunking);
  const uint64_t dechunkingStartUs = nowUs();
  if (!RadioFrame::decodeData(rfRx, length, messageId, decodedPacket, dataCrc)) {
    ++appErrors;
    Serial.printf("{\"event\":\"reject\",\"reason\":\"invalid_frame_crc_header_or_message\",\"time_us\":%llu}\n", arrival);
    resumeReceiver();
    return;
  }
  const uint8_t before = receiver->receivedChunkCount();
  if (!receiver->acceptPacket(reinterpret_cast<const uint8_t*>(&decodedPacket), sizeof(decodedPacket))) {
    ++appErrors;
    error("reassembly_rejected_packet");
    resumeReceiver();
    return;
  }
  const uint8_t index = decodedPacket.header.chunkIndex;
  const bool duplicate = before == receiver->receivedChunkCount();
  if (duplicate && memcmp(receiver->receiveBuffer() + index * Config::VOICE_CHUNK_PAYLOAD_BYTES,
                          decodedPacket.payload, Config::VOICE_CHUNK_PAYLOAD_BYTES) != 0) {
    ++appErrors;
    error("conflicting_duplicate_payload");
    resumeReceiver();
    return;
  }
  const uint64_t dechunkingUs = nowUs() - dechunkingStartUs;
  // Rejected frames return above without contributing a successful sample.
  // Duplicates exercise validation, but do not add to unique reassembly time.
  if (duplicate) {
    dechunkingDuplicateTotalUs += dechunkingUs;
    ++dechunkingDuplicateCount;
  } else {
    dechunkingTotalUs += dechunkingUs;
    ++dechunkingCount;
  }
  ++rxPackets;
  if (duplicate) ++duplicates;
  else {
    if (!firstRxUs) firstRxUs = arrival;
    if (!firstTransportRxUs) firstTransportRxUs = arrival;
    lastRxUs = arrival;
  }
  if (receiver->isComplete()) {
    if (gcmMode && !authenticateMessage()) { resumeReceiver(); return; }
    if (!gcmMode && !messageReadyUs) messageReadyUs = nowUs();
  }
  // Reassembly is finished before ACK turnaround; Last: DECHUNKING remains
  // visible without pretending that processing occupies the radio wait.
  LoraBenchDisplay::setState(DisplayState::Receiving);
  RadioFrame::encodeAck(messageId, index, dataCrc, ackFrame);
  // Allow the transmitting node to finish TX and enable RX before the reply.
  delay(ACK_TURNAROUND_MS);
  ++rfTxCallsTotal;
  const int16_t ackStatus = radio.transmit(ackFrame, sizeof(ackFrame));
  if (ackStatus == RADIOLIB_ERR_NONE) ++ackPackets;
  const int16_t resumeStatus = startReceive();
  Serial.printf("{\"event\":\"rx_packet\",\"id\":%u,\"index\":%u,\"rx_us\":%llu,"
                "\"duplicate\":%s,\"data_crc32\":\"%08lx\",\"rssi_dbm\":%.2f,"
                "\"snr_db\":%.2f,\"ack_status\":%d,\"dechunking_us\":%llu}\n",
                messageId, index, arrival, duplicate ? "true" : "false",
                static_cast<unsigned long>(dataCrc), rssi, snr, ackStatus, dechunkingUs);
  if (resumeStatus != RADIOLIB_ERR_NONE) {
    armed = false;
    LoraBenchDisplay::setState(DisplayState::Idle);
    error("receive_restart_failed");
  } else LoraBenchDisplay::setState(DisplayState::Receiving);
  if (receiver->isComplete() && !completeReported) {
    completeReported = true;
    Serial.printf("{\"event\":\"rx_complete\",\"id\":%u,\"received_chunks\":%u,"
                  "\"first_rx_us\":%llu,\"last_rx_us\":%llu,"
                  "\"dechunking_total_us\":%llu,\"dechunking_count\":%lu,"
                  "\"dechunking_duplicate_total_us\":%llu,\"dechunking_duplicate_count\":%lu,"
                  "\"mode\":\"%s\",\"authenticated\":%s,\"decryption_us\":%llu,"
                  "\"message_ready_us\":%llu,\"first_transport_rx_us\":%llu}\n",
                  messageId, receiver->receivedChunkCount(), firstRxUs, lastRxUs,
                  dechunkingTotalUs, static_cast<unsigned long>(dechunkingCount),
                  dechunkingDuplicateTotalUs, static_cast<unsigned long>(dechunkingDuplicateCount),
                  modeName(), authenticated ? "true" : "false", decryptionUs, messageReadyUs, firstTransportRxUs);
  }
}

void serviceSerial();

bool transmitMetadata(uint16_t id, unsigned& attempts, unsigned& successful,
                      unsigned& receivedAcks, uint64_t& radioStartUs) {
  const uint32_t crc = CryptoRadioFrame::metadataCrc(metadata);
  for (unsigned attempt = 1; attempt <= MAX_ATTEMPTS && !cancelled; ++attempt) {
    ++attempts;
    radio.standby(); clearIrqFlag();
    const uint64_t start = nowUs();
    if (!radioStartUs) radioStartUs = start;
    ++rfTxCallsTotal;
    int16_t result = radio.transmit(metadata, sizeof(metadata));
    const int16_t txStatus = result;
    const uint64_t end = nowUs();
    uint64_t ackTime = 0;
    bool accepted = false;
    if (result == RADIOLIB_ERR_NONE) {
      ++successful;
      result = startReceive();
      const uint64_t deadline = nowUs() + ACK_TIMEOUT_MS * 1000ULL;
      while (result == RADIOLIB_ERR_NONE && nowUs() < deadline && !cancelled) {
        serviceSerial();
        uint64_t arrival = 0;
        if (takeIrq(arrival)) {
          const size_t length = radio.getPacketLength();
          const int16_t readStatus = length <= sizeof(rfRx) ? radio.readData(rfRx, length) : -9001;
          if (readStatus == RADIOLIB_ERR_NONE && CryptoRadioFrame::decodeMetadataAck(rfRx, length, id, crc)) {
            accepted = true; ackTime = arrival; ++receivedAcks; break;
          }
          result = startReceive();
        }
        delay(1);
      }
    }
    radio.standby();
    Serial.printf("{\"event\":\"tx_metadata\",\"id\":%u,\"attempt\":%u,\"start_us\":%llu,"
                  "\"end_us\":%llu,\"ack_us\":%llu,\"tx_radio_status\":%d,\"radio_status\":%d,"
                  "\"acked\":%s,\"metadata_crc32\":\"%08lx\",\"metadata_hex\":\"",
                  id, attempt, start, end, ackTime, txStatus, result, accepted ? "true" : "false",
                  static_cast<unsigned long>(crc));
    printHex(metadata, sizeof(metadata)); Serial.println("\"}");
    if (accepted) { delay(3); return true; }
    delay(10);
  }
  return false;
}

void transmitMessage(uint16_t id) {
  if (role != Role::Tx || !loaded || !radioReady) { error("tx_not_ready"); return; }
  messageId = id;
  transmitting = true;
  ++txRunsStarted;
  cancelled = false;
  chunkingTotalUs = 0;
  chunkingCount = 0;
  encryptionUs = 0;
  unsigned acknowledged = 0, attempts = 0, uniqueAttempted = 0, successfulTransmits = 0, receivedAcks = 0;
  unsigned metadataAttempts = 0, metadataSuccessful = 0, metadataAcks = 0;
  uint64_t radioStartUs = 0;
  const uint64_t begin = nowUs();
  bool metadataAcked = false;
  bool proceed = !gcmMode || sealMessage(id);
  if (gcmMode && proceed) {
    LoraBenchDisplay::setState(DisplayState::Transmitting);
    metadataAcked = transmitMetadata(id, metadataAttempts, metadataSuccessful, metadataAcks, radioStartUs);
    proceed = metadataAcked;
  }
  const uint8_t* wireData = gcmMode ? cryptoBuffer : txPcm;
  for (unsigned index = 0; proceed && index < Config::VOICE_TOTAL_CHUNKS && !cancelled; ++index) {
    LoraBenchDisplay::setState(DisplayState::Chunking);
    const uint64_t chunkingStartUs = nowUs();
    if (!RadioFrame::encodeData(wireData, id, static_cast<uint8_t>(index), rfTx, sizeof(rfTx))) break;
    const uint32_t dataCrc = AudioDiagnostics::crc32(rfTx, sizeof(VoicePacket));
    const uint64_t chunkingUs = nowUs() - chunkingStartUs;
    chunkingTotalUs += chunkingUs;
    ++chunkingCount;
    LoraBenchDisplay::setState(DisplayState::Transmitting);
    bool accepted = false;
    for (unsigned attempt = 1; attempt <= MAX_ATTEMPTS && !cancelled; ++attempt) {
      if (attempt == 1) ++uniqueAttempted;
      ++attempts;
      radio.standby();
      clearIrqFlag();
      const uint64_t start = nowUs();
      if (!radioStartUs) radioStartUs = start;
      ++rfTxCallsTotal;
      int16_t result = radio.transmit(rfTx, sizeof(rfTx));
      const int16_t txStatus = result;
      const uint64_t end = nowUs();
      uint64_t ackTime = 0;
      if (result == RADIOLIB_ERR_NONE) {
        ++successfulTransmits;
        result = startReceive();
        const uint64_t deadline = nowUs() + ACK_TIMEOUT_MS * 1000ULL;
        while (result == RADIOLIB_ERR_NONE && nowUs() < deadline && !cancelled) {
          serviceSerial();
          uint64_t arrival = 0;
          if (takeIrq(arrival)) {
            const size_t length = radio.getPacketLength();
            const int16_t readStatus = length <= sizeof(rfRx) ? radio.readData(rfRx, length) : -9001;
            if (readStatus == RADIOLIB_ERR_NONE && RadioFrame::decodeAck(rfRx, length, id, index, dataCrc)) {
              accepted = true;
              ackTime = arrival;
              ++receivedAcks;
              break;
            }
            result = startReceive();
          }
          delay(1);
        }
      }
      radio.standby();
      Serial.printf("{\"event\":\"tx_packet\",\"id\":%u,\"index\":%u,\"attempt\":%u,"
                    "\"start_us\":%llu,\"end_us\":%llu,\"ack_us\":%llu,\"radio_status\":%d,\"tx_radio_status\":%d,"
                    "\"acked\":%s,\"data_crc32\":\"%08lx\",\"chunking_us\":%llu}\n",
                    id, index, attempt, start, end, ackTime, result, txStatus, accepted ? "true" : "false",
                    static_cast<unsigned long>(dataCrc), attempt == 1 ? chunkingUs : 0ULL);
      if (accepted) { ++acknowledged; break; }
      delay(10);
    }
    if (!accepted) break;  // Fail explicitly; never report a partial message as delivered.
    delay(3);
  }
  radio.standby();
  transmitting = false;
  LoraBenchDisplay::setState(DisplayState::Idle);
  const uint64_t end = nowUs();
  Serial.printf("{\"event\":\"tx_done\",\"id\":%u,\"success\":%s,"
                "\"acked_chunks\":%u,\"attempts\":%u,\"retries\":%u,"
                "\"successful_transmits\":%u,\"start_us\":%llu,\"end_us\":%llu,"
                "\"data_bytes_sent\":%u,\"ack_bytes_received\":%u,\"cancelled\":%s,"
                "\"chunking_total_us\":%llu,\"chunking_count\":%lu,\"mode\":\"%s\","
                "\"encryption_us\":%llu,\"metadata_acked\":%s,\"metadata_attempts\":%u,"
                "\"metadata_successful_transmits\":%u,\"metadata_ack_received\":%u,\"radio_start_us\":%llu}\n",
                id, acknowledged == Config::VOICE_TOTAL_CHUNKS && !cancelled ? "true" : "false",
                acknowledged, attempts, attempts - uniqueAttempted,
                successfulTransmits, begin, end,
                successfulTransmits * static_cast<unsigned>(RadioFrame::DATA_BYTES),
                receivedAcks * static_cast<unsigned>(RadioFrame::ACK_BYTES), cancelled ? "true" : "false",
                chunkingTotalUs, static_cast<unsigned long>(chunkingCount), modeName(), encryptionUs,
                metadataAcked ? "true" : "false", metadataAttempts, metadataSuccessful, metadataAcks, radioStartUs);
}

void cryptoSelfTest() {
  mbedtls_gcm_context context;
  mbedtls_gcm_init(&context);
  uint8_t zeroKey[16] = {}, zeroNonce[12] = {}, plain[16] = {}, cipher[16] = {}, actualTag[16] = {}, output[16] = {};
  const uint8_t expectedCipher[16] = {0x03,0x88,0xda,0xce,0x60,0xb6,0xa3,0x92,0xf3,0x28,0xc2,0xb9,0x71,0xb2,0xfe,0x78};
  const uint8_t expectedTag[16] = {0xab,0x6e,0x47,0xd4,0x2c,0xec,0x13,0xbd,0xf5,0x3a,0x67,0xb2,0x12,0x57,0xbd,0xdf};
  bool known = mbedtls_gcm_setkey(&context, MBEDTLS_CIPHER_ID_AES, zeroKey, 128) == 0;
  known = known && mbedtls_gcm_crypt_and_tag(&context, MBEDTLS_GCM_ENCRYPT, sizeof(plain),
      zeroNonce, sizeof(zeroNonce), nullptr, 0, plain, cipher, sizeof(actualTag), actualTag) == 0;
  known = known && memcmp(cipher, expectedCipher, sizeof(cipher)) == 0 && memcmp(actualTag, expectedTag, sizeof(actualTag)) == 0;
  known = known && mbedtls_gcm_auth_decrypt(&context, sizeof(cipher), zeroNonce, sizeof(zeroNonce),
      nullptr, 0, actualTag, sizeof(actualTag), cipher, output) == 0 && memcmp(output, plain, sizeof(plain)) == 0;
  actualTag[0] ^= 1;
  const bool badTag = mbedtls_gcm_auth_decrypt(&context, sizeof(cipher), zeroNonce, sizeof(zeroNonce),
      nullptr, 0, actualTag, sizeof(actualTag), cipher, output) == MBEDTLS_ERR_GCM_AUTH_FAILED;
  actualTag[0] ^= 1; cipher[0] ^= 1;
  const bool badCipher = mbedtls_gcm_auth_decrypt(&context, sizeof(cipher), zeroNonce, sizeof(zeroNonce),
      nullptr, 0, actualTag, sizeof(actualTag), cipher, output) == MBEDTLS_ERR_GCM_AUTH_FAILED;
  cipher[0] ^= 1; zeroKey[0] = 1;
  bool badKey = mbedtls_gcm_setkey(&context, MBEDTLS_CIPHER_ID_AES, zeroKey, 128) == 0;
  badKey = badKey && mbedtls_gcm_auth_decrypt(&context, sizeof(cipher), zeroNonce, sizeof(zeroNonce),
      nullptr, 0, actualTag, sizeof(actualTag), cipher, output) == MBEDTLS_ERR_GCM_AUTH_FAILED;
  // Exercise the actual 48 kB PSRAM path before the measured radio cohorts.
  // These public test vectors never use the independently provisioned bench key.
  uint8_t* largePlain = static_cast<uint8_t*>(heap_caps_malloc(Config::AUDIO_BUFFER_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  uint8_t* largeCipher = static_cast<uint8_t*>(heap_caps_malloc(Config::AUDIO_BUFFER_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  bool psramRoundTrip = largePlain && largeCipher;
  if (psramRoundTrip) {
    zeroKey[0] = 0;
    for (size_t i = 0; i < Config::AUDIO_BUFFER_BYTES; ++i) largePlain[i] = static_cast<uint8_t>(i * 17U + 3U);
    psramRoundTrip = mbedtls_gcm_setkey(&context, MBEDTLS_CIPHER_ID_AES, zeroKey, 128) == 0 &&
        mbedtls_gcm_crypt_and_tag(&context, MBEDTLS_GCM_ENCRYPT, Config::AUDIO_BUFFER_BYTES,
            zeroNonce, sizeof(zeroNonce), nullptr, 0, largePlain, largeCipher, sizeof(actualTag), actualTag) == 0;
    memset(largePlain, 0, Config::AUDIO_BUFFER_BYTES);
    psramRoundTrip = psramRoundTrip && mbedtls_gcm_auth_decrypt(&context, Config::AUDIO_BUFFER_BYTES,
        zeroNonce, sizeof(zeroNonce), nullptr, 0, actualTag, sizeof(actualTag), largeCipher, largePlain) == 0;
    for (size_t i = 0; psramRoundTrip && i < Config::AUDIO_BUFFER_BYTES; ++i)
      psramRoundTrip = largePlain[i] == static_cast<uint8_t>(i * 17U + 3U);
  }
  if (largePlain) { mbedtls_platform_zeroize(largePlain, Config::AUDIO_BUFFER_BYTES); heap_caps_free(largePlain); }
  if (largeCipher) { mbedtls_platform_zeroize(largeCipher, Config::AUDIO_BUFFER_BYTES); heap_caps_free(largeCipher); }
  mbedtls_gcm_free(&context);
  mbedtls_platform_zeroize(output, sizeof(output));
  Serial.printf("{\"event\":\"crypto_selftest\",\"passed\":%s,\"known_answer_passed\":%s,"
                "\"wrong_key_rejected\":%s,\"wrong_tag_rejected\":%s,\"changed_ciphertext_rejected\":%s,"
                "\"psram_round_trip_passed\":%s}\n",
                known && badKey && badTag && badCipher && psramRoundTrip ? "true" : "false", known ? "true" : "false",
                badKey ? "true" : "false", badTag ? "true" : "false", badCipher ? "true" : "false",
                psramRoundTrip ? "true" : "false");
}

void handleCommand(const char* line) {
  unsigned long value = 0;
  char extra = 0;
  if (strcmp(line, "HELLO") == 0) { hello(); return; }
  if (sscanf(line, "TIME %lu %c", &value, &extra) == 1) {
    const uint64_t stamp = nowUs();
    Serial.printf("{\"event\":\"time\",\"token\":%lu,\"time_us\":%llu,\"boot_id\":\"%s\"}\n", value, stamp, bootId);
    return;
  }
  if (strcmp(line, "STOP") == 0) {
    cancelled = true;
    armed = false;
    if (radioReady) radio.standby();
    LoraBenchDisplay::setState(DisplayState::Idle);
    Serial.printf("{\"event\":\"stopped\",\"time_us\":%llu}\n", nowUs());
    return;
  }
  if (strcmp(line, "STATUS") == 0) { status(); return; }
  if (transmitting) { error("busy_transmitting"); return; }
  if (armed) { error("busy_receiving"); return; }
  if (strcmp(line, "CRYPTOSELFTEST") == 0) { cryptoSelfTest(); return; }
  if (strcmp(line, "MODE PLAIN") == 0 || strcmp(line, "MODE GCM") == 0) {
    gcmMode = strcmp(line, "MODE GCM") == 0;
    resetCryptoMessage(); resetProcessingTimings();
    loaded = false; completeReported = false;
    if (txPcm) { heap_caps_free(txPcm); txPcm = nullptr; }
    if (receiver) { receiver->~VoiceChunker(); heap_caps_free(receiver); receiver = nullptr; }
    if (cryptoBuffer) { mbedtls_platform_zeroize(cryptoBuffer, Config::AUDIO_BUFFER_BYTES); heap_caps_free(cryptoBuffer); cryptoBuffer = nullptr; }
    role = Role::None;
    allocationRequested = allocationActual = cryptoAllocationActual = 0;
    Serial.printf("{\"event\":\"mode\",\"mode\":\"%s\"}\n", modeName());
    return;
  }
  if (strncmp(line, "KEY ", 4) == 0) {
    uint8_t parsed[sizeof(cryptoKey)] = {};
    if (!parseHex(line + 4, parsed, sizeof(parsed))) {
      mbedtls_platform_zeroize(parsed, sizeof(parsed)); error("invalid_key"); return;
    }
    const int32_t before = static_cast<int32_t>(ESP.getFreeHeap());
    const uint64_t start = nowUs();
    const int result = mbedtls_gcm_setkey(&cryptoContext, MBEDTLS_CIPHER_ID_AES, parsed, 128);
    keySetupUs = nowUs() - start;
    cryptoLibraryHeapDelta = before - static_cast<int32_t>(ESP.getFreeHeap());
    keyReady = result == 0;
    if (keyReady) memcpy(cryptoKey, parsed, sizeof(cryptoKey));
    else mbedtls_platform_zeroize(cryptoKey, sizeof(cryptoKey));
    mbedtls_platform_zeroize(parsed, sizeof(parsed));
    resetCryptoMessage(); loaded = false;
    Serial.printf("{\"event\":\"key\",\"key_ready\":%s,\"key_setup_us\":%llu}\n",
                  keyReady ? "true" : "false", keySetupUs);
    return;
  }
  if (strncmp(line, "NONCE ", 6) == 0) {
    uint8_t parsed[sizeof(nonce)] = {};
    if (!gcmMode || !keyReady || role != Role::Tx || !parseHex(line + 6, parsed, sizeof(parsed))) {
      error("invalid_nonce_or_role"); return;
    }
    memcpy(nonce, parsed, sizeof(nonce)); nonceReady = true; sealed = false;
    Serial.print("{\"event\":\"nonce\",\"nonce_hex\":\""); printHex(nonce, sizeof(nonce)); Serial.println("\"}");
    return;
  }
  unsigned long total = 0;
  if (sscanf(line, "TEST %lu %lu %c", &value, &total, &extra) == 2) {
    if (armed) { error("test_metadata_requires_standby"); return; }
    if (total < 1 || total > 100 || value > total ||
        !LoraBenchDisplay::setTest(static_cast<uint16_t>(value), static_cast<uint16_t>(total))) {
      error("invalid_test_counter"); return;
    }
    Serial.printf("{\"event\":\"test\",\"current\":%lu,\"total\":%lu,\"time_us\":%llu}\n",
                  value, total, nowUs());
    return;
  }
  if (strcmp(line, "ROLE TX") == 0) { setRole(Role::Tx); return; }
  if (strcmp(line, "ROLE RX") == 0) { setRole(Role::Rx); return; }
  if (sscanf(line, "LOAD %lx %c", &value, &extra) == 1) { loadPcm(static_cast<uint32_t>(value)); return; }
  if (sscanf(line, "ARM %lu %c", &value, &extra) == 1) {
    if (role != Role::Rx || !receiver || !radioReady || value == 0 || value > 65535) {
      error("invalid_arm"); return;
    }
    if (gcmMode && (!keyReady || !cryptoBuffer)) { error("arm_requires_crypto_key_and_buffer"); return; }
    radio.standby();
    messageId = static_cast<uint16_t>(value);
    receiver->beginReceive(messageId);
    resetProcessingTimings();
    resetCryptoMessage();
    if (cryptoBuffer) memset(cryptoBuffer, 0, Config::AUDIO_BUFFER_BYTES);
    duplicates = crcErrors = appErrors = rxPackets = ackPackets = 0;
    firstRxUs = lastRxUs = 0;
    completeReported = false;
    const int16_t result = startReceive();
    armed = result == RADIOLIB_ERR_NONE;
    if (!armed) { error("arm_radio_failed"); return; }
    LoraBenchDisplay::setState(DisplayState::Receiving);
    Serial.printf("{\"event\":\"armed\",\"id\":%u,\"time_us\":%llu}\n", messageId, nowUs());
    return;
  }
  if (sscanf(line, "TX %lu %c", &value, &extra) == 1) {
    if (value == 0 || value > 65535) { error("invalid_message_id"); return; }
    transmitMessage(static_cast<uint16_t>(value)); return;
  }
  if (strcmp(line, "DUMP TX") == 0) { dump(true); return; }
  if (strcmp(line, "DUMP RX") == 0) { dump(false); return; }
  if (strcmp(line, "DUMP CIPHER") == 0) { dumpCipher(); return; }
  error("unknown_command");
}

void serviceSerial() {
  while (Serial.available()) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\r') continue;
    if (value == '\n') {
      if (discardCommand) error("command_too_long");
      else if (commandLength) {
        command[commandLength] = 0;
        // Reset parser before dispatch because TX services serial while waiting.
        char ready[sizeof(command)];
        memcpy(ready, command, commandLength + 1);
        commandLength = 0;
        mbedtls_platform_zeroize(command, sizeof(command));
        handleCommand(ready);
        mbedtls_platform_zeroize(ready, sizeof(ready));
      }
      commandLength = 0;
      discardCommand = false;
    } else if (!discardCommand) {
      if (commandLength + 1 < sizeof(command)) command[commandLength++] = value;
      else discardCommand = true;
    }
  }
}
}  // namespace

void setup() {
  mbedtls_gcm_init(&cryptoContext);
  pinMode(48, OUTPUT);
  digitalWrite(48, LOW);  // Amplifier stays muted; no audio drivers or clocks.
  // Native USB is faster than the selected baud; block acknowledgements keep
  // the host from overflowing this bounded queue while loading PCM into PSRAM.
  Serial.setRxBufferSize(4096);
  Serial.begin(115200);
  const uint32_t serialDeadline = millis() + 2000;
  while (!Serial && millis() < serialDeadline) delay(10);
  uint8_t mac[6] = {};
  esp_efuse_mac_get_default(mac);
  snprintf(deviceMac, sizeof(deviceMac), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  snprintf(bootId, sizeof(bootId), "%s-%08lx", deviceMac, static_cast<unsigned long>(esp_random()));
  LoraBenchDisplay::begin(NODE_LABEL);
  // V4.3 KCT8103L: DIO2 handles CPS, CTX HIGH gives RX bypass / TX.
  pinMode(7, OUTPUT); digitalWrite(7, HIGH); delay(1);
  pinMode(2, OUTPUT); digitalWrite(2, HIGH); delay(1);
  pinMode(5, OUTPUT); digitalWrite(5, HIGH); delay(2);
  SPI.begin(9, 11, 10, 8);
  radioInitStatus = radio.begin(FREQUENCY_MHZ, BANDWIDTH_KHZ, SPREADING_FACTOR,
                                CODING_RATE, 0x12, CHIP_POWER_DBM, 8, 1.8f, false);
  if (radioInitStatus == RADIOLIB_ERR_NONE) radioInitStatus = radio.setDio2AsRfSwitch(true);
  if (radioInitStatus == RADIOLIB_ERR_NONE) radioInitStatus = radio.setCRC(2);
  if (radioInitStatus == RADIOLIB_ERR_NONE) radioInitStatus = radio.applyReceivePatch();
  radioReady = radioInitStatus == RADIOLIB_ERR_NONE;
  if (radioReady) {
    radio.setPacketReceivedAction(onDio1);
    radio.standby();
  } else {
    digitalWrite(2, LOW);
    digitalWrite(7, LOW);
  }
  // Allocate the initial displayed roles, but never arm or transmit at boot.
  if (radioReady) setRole(LORA_BENCH_NODE_ID == 6 ? Role::Tx : Role::Rx);
  LoraBenchDisplay::setState(DisplayState::Idle);
  hello();
}

void loop() {
  serviceSerial();
  if (armed && role == Role::Rx && receiver) receivePacket();
  delay(1);
}
#endif
