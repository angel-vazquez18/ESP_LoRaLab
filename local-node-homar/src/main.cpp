#include <Arduino.h>
#include <esp_system.h>
#include <esp_arduino_version.h>

#include "audio_manager.h"
#include "audio_diagnostics.h"
#include "board_bench.h"
#include "chunker.h"
#include "config.h"
#include "pins.h"
#include "protocol.h"

namespace {

enum class TestState : uint8_t {
  IDLE,
  RECORDING,
  CHUNKING,
  PLAYBACK
};

AudioManager audio;
VoiceChunker chunker;

// Static buffers: do not move these to function stack.
// 48,000 bytes TX + 48,000 bytes RX inside VoiceChunker.
uint8_t txAudioBuffer[Config::AUDIO_BUFFER_BYTES];
bool recordingValid = false;

TestState state = TestState::IDLE;

uint16_t nextMessageId = 1;

bool previousPttState = false;
bool heartbeatEnabled = true;
uint8_t simulatedDropEveryN = Config::SIMULATED_DROP_EVERY_N;

const char* stateName(TestState currentState) {
  switch (currentState) {
    case TestState::IDLE:
      return "IDLE";

    case TestState::RECORDING:
      return "RECORDING";

    case TestState::CHUNKING:
      return "CHUNKING";

    case TestState::PLAYBACK:
      return "PLAYBACK";
  }

  return "UNKNOWN";
}

void setState(TestState newState) {
  state = newState;
  Serial.printf("\n[STATE] %s\n", stateName(state));
  BoardBench::showStatus(stateName(state), audio.microphoneReady(), audio.speakerReady());
}

bool pttPressed() {
  return digitalRead(Pins::PTT_BUTTON) == LOW;
}

void printBanner() {
  Serial.println();
  Serial.println("==============================================");
  Serial.println(" ESP32 Audio / Voice Chunker Hardware Test");
  Serial.println(" Diagnostic revision: audio-bench-7-scope-tone");
  Serial.println("==============================================");
  Serial.println("Audio format:");
  Serial.printf("  %lu Hz, %u-bit, mono, %lu seconds\n",
                static_cast<unsigned long>(Config::AUDIO_SAMPLE_RATE_HZ),
                static_cast<unsigned>(Config::AUDIO_BITS_PER_SAMPLE),
                static_cast<unsigned long>(Config::RECORD_SECONDS));
  Serial.printf("  PCM buffer: %u bytes\n",
                static_cast<unsigned>(Config::AUDIO_BUFFER_BYTES));
  Serial.printf("  Chunk payload: %u bytes\n",
                static_cast<unsigned>(Config::VOICE_CHUNK_PAYLOAD_BYTES));
  Serial.printf("  Packet count: %u\n",
                static_cast<unsigned>(Config::VOICE_TOTAL_CHUNKS));
  Serial.printf("  Voice packet size: %u bytes\n",
                static_cast<unsigned>(sizeof(VoicePacket)));
  Serial.println();
  Serial.println("Commands:");
  Serial.println("  r = record then direct playback");
  Serial.println("  p = record, packetize, simulated transport, playback");
  Serial.println("  t = deterministic chunker integrity test");
  Serial.println("  s = play 1 kHz speaker test tone");
  Serial.println("  b = play continuous 15-second 1 kHz tone for scope capture");
  Serial.println("  m = microphone capture/statistics only");
  Serial.println("  d = export last recording as binary PCM (use tools/capture_audio.py)");
  Serial.println("  l = toggle simulated loss: 0 / every 17th index");
  Serial.println("  h = toggle diagnostic heartbeat");
  Serial.println("  i = print system information");
  Serial.println("  v = probe speaker clock/enable pins (Heltec)");
  Serial.println("  x = print protocol information");
  Serial.printf("  PTT button: %s\n", Config::ENABLE_PTT ? "enabled (same as p)" : "disabled");
  Serial.println("==============================================");
}

void printSystemInformation() {
  Serial.println();
  Serial.println("[SYSTEM]");
  BoardBench::printIdentity();
  Serial.printf("Build: %s %s, Arduino %s, IDF %s\n", __DATE__, __TIME__,
                ESP_ARDUINO_VERSION_STR, ESP.getSdkVersion());
  Serial.printf("Reset reason: %d, uptime: %lu ms\n", static_cast<int>(esp_reset_reason()),
                static_cast<unsigned long>(millis()));
  Serial.printf("Free heap: %u bytes\n",
                static_cast<unsigned>(ESP.getFreeHeap()));
  Serial.printf("Minimum free heap: %u bytes\n",
                static_cast<unsigned>(ESP.getMinFreeHeap()));
  Serial.printf("TX audio buffer: %u bytes\n",
                static_cast<unsigned>(sizeof(txAudioBuffer)));
  Serial.printf("RX audio buffer: %u bytes\n",
                static_cast<unsigned>(Config::AUDIO_BUFFER_BYTES));
  Serial.printf("Chunk bitmap: %u bytes\n",
                static_cast<unsigned>(
                    (Config::VOICE_TOTAL_CHUNKS + 7) / 8));
  Serial.printf("Simulated drop interval: %u\n",
                static_cast<unsigned>(simulatedDropEveryN));
  audio.printDiagnostics();
}

void printProtocolInformation() {
  Serial.println();
  Serial.println("[PROTOCOL]");
  Serial.printf("Magic: 0x%02X\n", Config::VOICE_PROTOCOL_MAGIC);
  Serial.printf("Version: %u\n", Config::VOICE_PROTOCOL_VERSION);
  Serial.printf("Header bytes: %u\n",
                static_cast<unsigned>(sizeof(VoicePacketHeader)));
  Serial.printf("Payload bytes: %u\n",
                static_cast<unsigned>(Config::VOICE_CHUNK_PAYLOAD_BYTES));
  Serial.printf("Packet bytes: %u\n",
                static_cast<unsigned>(sizeof(VoicePacket)));
  Serial.printf("Total chunks: %u\n",
                static_cast<unsigned>(Config::VOICE_TOTAL_CHUNKS));

  Serial.println("Header layout:");
  Serial.println("  byte 0: magic");
  Serial.println("  byte 1: version");
  Serial.println("  byte 2-3: message ID");
  Serial.println("  byte 4: chunk index");
  Serial.println("  byte 5: total chunks");
  Serial.println("  byte 6: payload length");
}

void fillDeterministicPattern(uint8_t* buffer, size_t length) {
  for (size_t i = 0; i < length; ++i) {
    buffer[i] = static_cast<uint8_t>((i * 37U + 11U) & 0xFFU);
  }
}

bool compareBuffers(const uint8_t* first,
                    const uint8_t* second,
                    size_t length,
                    size_t& firstMismatch) {
  for (size_t i = 0; i < length; ++i) {
    if (first[i] != second[i]) {
      firstMismatch = i;
      return false;
    }
  }

  firstMismatch = 0;
  return true;
}

void runChunkerIntegrityTest() {
  Serial.println();
  Serial.println("[TEST] Starting deterministic chunker test");

  // Fill the global TX buffer with predictable non-audio data.
  recordingValid = false;
  fillDeterministicPattern(txAudioBuffer, sizeof(txAudioBuffer));

  // IMPORTANT:
  // Do NOT create VoiceChunker as a local variable here.
  // VoiceChunker contains a 48 KB RX buffer and would overflow
  // the Arduino loop task stack.
  //
  // Reuse the already-global chunker object instead.
  chunker.resetReceive();

  VoicePacket packet;

  constexpr uint16_t testMessageId = 0x1234;

  chunker.beginTransmit(txAudioBuffer, testMessageId);

  // Send packets in reverse order. This confirms reconstruction
  // uses chunk indexes rather than arrival order.
  for (int chunkIndex = Config::VOICE_TOTAL_CHUNKS - 1;
       chunkIndex >= 0;
       --chunkIndex) {
    if (!chunker.makePacket(
            static_cast<uint8_t>(chunkIndex),
            packet)) {
      Serial.printf("[TEST] Packet creation failed at chunk %d\n",
                    chunkIndex);
      chunker.resetReceive();
      return;
    }

    if (!chunker.acceptPacket(
            reinterpret_cast<const uint8_t*>(&packet),
            sizeof(packet))) {
      Serial.printf("[TEST] Packet acceptance failed at chunk %d\n",
                    chunkIndex);
      chunker.resetReceive();
      return;
    }

    // Feed the watchdog during this CPU-only test.
    if ((chunkIndex % 20) == 0) {
      delay(1);
    }
  }

  if (!chunker.isComplete()) {
    Serial.printf("[TEST] FAIL: incomplete reassembly. "
                  "received=%u missing=%u\n",
                  static_cast<unsigned>(chunker.receivedChunkCount()),
                  static_cast<unsigned>(chunker.missingChunkCount()));

    chunker.resetReceive();
    return;
  }

  size_t mismatchOffset = 0;

  const bool identical = compareBuffers(
      txAudioBuffer,
      chunker.receiveBuffer(),
      Config::AUDIO_BUFFER_BYTES,
      mismatchOffset);

  if (!identical) {
    Serial.printf("[TEST] FAIL: mismatch at byte %lu\n",
                  static_cast<unsigned long>(mismatchOffset));

    chunker.resetReceive();
    return;
  }

  Serial.println("[TEST] PASS: 200 packets reassembled correctly");
  Serial.println("[TEST] PASS: reverse-order indexed reassembly works");

  // Clear the global RX buffer after test completion.
  chunker.resetReceive();
}

void recordAudio() {
  recordingValid = false;
  Serial.println();
  Serial.println("[AUDIO] Speak now. Recording for 3 seconds...");

  const uint32_t startTime = millis();

  const bool result =
      audio.recordThreeSeconds(txAudioBuffer, sizeof(txAudioBuffer));

  const uint32_t elapsed = millis() - startTime;

  if (!result) {
    Serial.println("[AUDIO] Recording failed");
    setState(TestState::IDLE);
    return;
  }

  recordingValid = true;
  Serial.printf("[AUDIO] Recording complete in %lu ms\n",
                static_cast<unsigned long>(elapsed));
}

void exportRecording() {
  if (!recordingValid) {
    Serial.println("[PCM ERROR] No complete recording; use m, r or p first");
    return;
  }
  // The loop/heartbeat cannot interleave with this synchronous command. Do not
  // log inside the payload. Capture first, transfer afterwards; no live stream.
  const uint32_t crc = AudioDiagnostics::crc32(txAudioBuffer, sizeof(txAudioBuffer));
  Serial.printf("\n[PCM_BEGIN] bytes=%u rate=%lu bits=16 channels=1 crc32=%08lx\n",
      static_cast<unsigned>(sizeof(txAudioBuffer)),
      static_cast<unsigned long>(Config::AUDIO_SAMPLE_RATE_HZ),
      static_cast<unsigned long>(crc));
  size_t sent = 0;
  uint32_t lastProgress = millis();
  while (sent < sizeof(txAudioBuffer)) {
    const int capacity = Serial.availableForWrite();
    if (capacity > 0) {
      size_t amount = sizeof(txAudioBuffer) - sent;
      if (amount > static_cast<size_t>(capacity)) amount = capacity;
      if (amount > 64) amount = 64;
      const size_t written = Serial.write(txAudioBuffer + sent, amount);
      if (written > amount) break;
      if (written) { sent += written; lastProgress = millis(); }
    }
    if (millis() - lastProgress > 2000) break;
    delay(1);
  }
  if (sent != sizeof(txAudioBuffer)) {
    Serial.println("\n[PCM ERROR] Serial export stalled; discard incomplete payload");
    return;
  }
  Serial.println("\n[PCM_END]");
}

void directRecordAndPlayback() {
  setState(TestState::RECORDING);

  recordAudio();

  if (state == TestState::IDLE) {
    return;
  }

  setState(TestState::PLAYBACK);

  Serial.println("[AUDIO] Direct PCM playback...");
  const bool played = audio.playPcm(txAudioBuffer, sizeof(txAudioBuffer));
  Serial.println(played ? "[AUDIO] Direct playback complete (digital path)"
                        : "[AUDIO] Direct playback FAILED");
  setState(TestState::IDLE);
}

bool simulatedPacketTransfer() {
  const uint16_t messageId = nextMessageId++;
  VoicePacket packet;

  chunker.resetReceive();
  chunker.beginTransmit(txAudioBuffer, messageId);

  Serial.printf("[CHUNK] Simulating message ID %u\n", messageId);
  Serial.printf("[CHUNK] Creating %u packets\n",
                static_cast<unsigned>(Config::VOICE_TOTAL_CHUNKS));

  uint8_t intentionallyDropped = 0;
  uint8_t acceptedPackets = 0;

  for (uint8_t chunkIndex = 0;
       chunkIndex < Config::VOICE_TOTAL_CHUNKS;
       ++chunkIndex) {
    if (!chunker.makePacket(chunkIndex, packet)) {
      Serial.printf("[CHUNK] Failed to create packet %u\n", chunkIndex);
      continue;
    }

    bool shouldDrop = false;

    if (simulatedDropEveryN > 0 &&
        chunkIndex > 0 &&
        (chunkIndex % simulatedDropEveryN) == 0) {
      shouldDrop = true;
    }

    if (shouldDrop) {
      ++intentionallyDropped;

      Serial.printf("[CHUNK] Simulated drop: %u\n", chunkIndex);
      continue;
    }

    const bool accepted = chunker.acceptPacket(
        reinterpret_cast<const uint8_t*>(&packet),
        sizeof(packet));

    if (!accepted) {
      Serial.printf("[CHUNK] Reassembler rejected packet %u\n",
                    chunkIndex);
      continue;
    }

    ++acceptedPackets;

    if ((chunkIndex % 25) == 0 ||
        chunkIndex == Config::VOICE_TOTAL_CHUNKS - 1) {
      Serial.printf("[CHUNK] Processed %u/%u\n",
                    chunkIndex + 1,
                    Config::VOICE_TOTAL_CHUNKS);
    }
  }

  Serial.println();
  Serial.printf("[CHUNK] Simulated TX complete\n");
  Serial.printf("[CHUNK] Accepted packets: %u\n", acceptedPackets);
  Serial.printf("[CHUNK] Deliberately dropped: %u\n",
                intentionallyDropped);
  Serial.printf("[CHUNK] RX chunks received: %u\n",
                chunker.receivedChunkCount());
  Serial.printf("[CHUNK] RX chunks missing: %u\n",
                chunker.missingChunkCount());

  if (chunker.isComplete()) {
    Serial.println("[CHUNK] Message complete: no loss");
  } else {
    Serial.println("[CHUNK] Partial message: missing chunks are PCM silence");
  }

  // Verify the actual recorded PCM, including byte-exact zero filling.
  if (acceptedPackets + intentionallyDropped != Config::VOICE_TOTAL_CHUNKS ||
      chunker.missingChunkCount() != intentionallyDropped) return false;
  for (size_t i = 0; i < sizeof(txAudioBuffer); ++i) {
    const size_t index = i / Config::VOICE_CHUNK_PAYLOAD_BYTES;
    const bool dropped = simulatedDropEveryN > 0 && index > 0 &&
                         index % simulatedDropEveryN == 0;
    const uint8_t expected = dropped ? 0 : txAudioBuffer[i];
    if (chunker.receiveBuffer()[i] != expected) {
      Serial.printf("[CHUNK] FAIL: mismatch at byte %u\n", static_cast<unsigned>(i));
      return false;
    }
  }
  Serial.println("[CHUNK] PASS: PCM and missing-chunk silence verified byte-for-byte");
  return true;
}

void recordChunkAndPlayback() {
  setState(TestState::RECORDING);

  recordAudio();

  if (state == TestState::IDLE) {
    return;
  }

  setState(TestState::CHUNKING);

  if (!simulatedPacketTransfer()) {
    Serial.println("[CHUNK] Transfer validation FAILED");
    chunker.resetReceive();
    setState(TestState::IDLE);
    return;
  }

  setState(TestState::PLAYBACK);

  Serial.println("[AUDIO] Playing reassembled PCM...");
  const bool played = audio.playPcm(chunker.receiveBuffer(), Config::AUDIO_BUFFER_BYTES);
  Serial.println(played ? "[AUDIO] Reassembled playback complete (digital path)"
                        : "[AUDIO] Reassembled playback FAILED");

  chunker.resetReceive();

  setState(TestState::IDLE);
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    const char command = static_cast<char>(Serial.read());

    switch (command) {
      case 'r':
      case 'R':
        if (state == TestState::IDLE) {
          directRecordAndPlayback();
        }
        break;

      case 'p':
      case 'P':
        if (state == TestState::IDLE) {
          recordChunkAndPlayback();
        }
        break;

      case 't':
      case 'T':
        if (state == TestState::IDLE) {
          runChunkerIntegrityTest();
        }
        break;
        
      case 's':
      case 'S':
      case 'b':
      case 'B':
        if (state == TestState::IDLE) {
          const uint32_t durationMs = (command == 'b' || command == 'B') ? 15000 : 1000;
          setState(TestState::PLAYBACK);
          BoardBench::showStatus("1 kHz tone", audio.microphoneReady(), audio.speakerReady());
          Serial.println("[AUDIO] Playing 1 kHz speaker test tone...");
          BoardBench::beginToneProbe();
          const bool played = audio.playTestTone(durationMs);
          BoardBench::endToneProbe();
          Serial.println(played ? "[AUDIO] Tone transfer complete; verify audible output"
                                : "[AUDIO] Tone test FAILED (I2S unavailable/error)");
          setState(TestState::IDLE);
        }
        break;

      case 'm':
      case 'M':
        if (state == TestState::IDLE) {
          setState(TestState::RECORDING);
          recordAudio();
          setState(TestState::IDLE);
        }
        break;

      case 'l':
      case 'L':
        simulatedDropEveryN = simulatedDropEveryN == 0 ? 17 : 0;
        Serial.printf("[CHUNK] Drop interval now %u (applies to p/PTT)\n", simulatedDropEveryN);
        break;

      case 'd':
      case 'D':
        if (state == TestState::IDLE) exportRecording();
        break;

      case 'h':
      case 'H':
        heartbeatEnabled = !heartbeatEnabled;
        Serial.printf("[HEARTBEAT] %s\n", heartbeatEnabled ? "enabled" : "disabled");
        break;

      case 'i':
      case 'I':
        printSystemInformation();
        break;

      case 'v':
      case 'V':
        if (state == TestState::IDLE) BoardBench::printSpeakerPins();
        break;

      case 'x':
      case 'X':
        printProtocolInformation();
        break;

      case '\r':
      case '\n':
      case ' ':
        break;

      default:
        Serial.printf("Unknown command: %c\n", command);
        break;
    }
  }
}

void handlePtt() {
  const bool currentPttState = pttPressed();

  // Trigger on press edge, not continuously while held.
  if (currentPttState && !previousPttState &&
      state == TestState::IDLE) {
    delay(25);

    if (pttPressed()) {
      recordChunkAndPlayback();
    }
  }

  previousPttState = currentPttState;
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(1000);

  // Leave the unused PTT pad untouched until the physical button is introduced.
  if (Config::ENABLE_PTT) pinMode(Pins::PTT_BUTTON, INPUT_PULLUP);

  BoardBench::begin();

  printBanner();

  Serial.println("[INIT] Starting I2S drivers...");

  if (!audio.begin()) {
    Serial.println("[INIT] One or more requested I2S drivers failed; diagnostics remain available");
  } else {
    Serial.println("[INIT] Requested I2S drivers initialized (see ready flags)");
  }
  printSystemInformation();

  setState(TestState::IDLE);
}

void loop() {
  static uint32_t lastHeartbeatMs = 0;

  handleSerialCommands();

  if (Config::ENABLE_PTT) handlePtt();

  if (heartbeatEnabled && millis() - lastHeartbeatMs >= 1000) {
    lastHeartbeatMs = millis();
    Serial.printf("[HEARTBEAT] uptime=%lu ms heap=%u state=%s\n",
        static_cast<unsigned long>(millis()), static_cast<unsigned>(ESP.getFreeHeap()), stateName(state));
  }

  delay(50);
}
