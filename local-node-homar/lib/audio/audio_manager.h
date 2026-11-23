#pragma once

#include <stddef.h>
#include <stdint.h>

class AudioManager {
 public:
  bool begin();
  bool microphoneReady() const { return microphoneReady_; }
  bool speakerReady() const { return speakerReady_; }
  void printDiagnostics() const;

  bool recordThreeSeconds(uint8_t* destination, size_t destinationBytes);

  bool playPcm(const uint8_t* source, size_t sourceBytes);

  bool playTestTone(uint32_t durationMs = 1000);

  void stopSpeaker();

 private:
  bool configureMicrophoneI2S();
  bool configureSpeakerI2S();
  bool microphoneReady_ = false;
  bool speakerReady_ = false;
  bool beginCalled_ = false;
  bool beginResult_ = false;
};
