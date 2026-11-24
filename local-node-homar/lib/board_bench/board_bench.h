#pragma once

// Board-specific bench identity and display. The original ESP32 bench has no
// onboard display; these functions are no-ops for that build.
namespace BoardBench {

void begin();
void printIdentity();
void printSpeakerPins();
void beginToneProbe();
void endToneProbe();
void showStatus(const char* status, bool microphoneReady, bool speakerReady);

}  // namespace BoardBench
