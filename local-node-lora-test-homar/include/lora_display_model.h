#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

// Portable display state only: no Arduino, radio, delays, or hardware access.
namespace LoraDisplayModel {

enum class State { Idle, Chunking, Transmitting, Receiving, Dechunking };

inline const char* stateName(State state) {
  switch (state) {
    case State::Idle: return "IDLE";
    case State::Chunking: return "CHUNKING";
    case State::Transmitting: return "TRANSMITTING";
    case State::Receiving: return "RECEIVING";
    case State::Dechunking: return "DECHUNKING";
  }
  return "UNKNOWN";
}

constexpr size_t ROW_COUNT = 5;
constexpr size_t ROW_BYTES = 32;
constexpr uint8_t ROW_Y[ROW_COUNT] = {0, 12, 25, 38, 51};
struct Rows { char text[ROW_COUNT][ROW_BYTES]; };

class Model {
 public:
  bool setNodeLabel(const char* label) {
    if (label == nullptr || label[0] == '\0' || strlen(label) >= sizeof(nodeLabel_)) return false;
    memset(nodeLabel_, 0, sizeof(nodeLabel_));
    memcpy(nodeLabel_, label, strlen(label));
    return true;
  }

  void setRole(bool transmitter) { transmitter_ = transmitter; }

  void setState(State next) {
    switch (next) {
      case State::Chunking:
      case State::Dechunking:
        lastProcessing_ = next;
        hasLastProcessing_ = true;
        break;
      case State::Idle:
      case State::Transmitting:
      case State::Receiving:
        break;
      default:
        return;
    }
    state_ = next;
  }

  bool setTest(uint16_t current, uint16_t total) {
    if (total == 0 || total > 100 || current > total) return false;
    currentTest_ = current;
    totalTests_ = total;
    state_ = State::Idle;
    hasLastProcessing_ = false;
    return true;
  }

  State state() const { return state_; }
  bool transmitter() const { return transmitter_; }
  uint16_t currentTest() const { return currentTest_; }
  uint16_t totalTests() const { return totalTests_; }

  bool formatRows(Rows& rows) const {
    // Deterministic unused bytes permit cheap snapshot comparisons in the task.
    memset(&rows, 0, sizeof(rows));
    memcpy(rows.text[0], nodeLabel_, sizeof(nodeLabel_));
    const int lengths[] = {
        snprintf(rows.text[1], ROW_BYTES, "Role: %s", transmitter_ ? "Transmitter" : "Receiver"),
        snprintf(rows.text[2], ROW_BYTES, "Status: %s", stateName(state_)),
        snprintf(rows.text[3], ROW_BYTES, "Last: %s", hasLastProcessing_ ? stateName(lastProcessing_) : "--"),
        snprintf(rows.text[4], ROW_BYTES, "Test %u of %u", static_cast<unsigned>(currentTest_),
                 static_cast<unsigned>(totalTests_))};
    for (int length : lengths) {
      if (length < 0 || static_cast<size_t>(length) >= ROW_BYTES) return false;
    }
    return true;
  }

 private:
  char nodeLabel_[ROW_BYTES] = "Heltec LoRa";
  State state_ = State::Idle;
  State lastProcessing_ = State::Idle;
  bool transmitter_ = false;
  bool hasLastProcessing_ = false;
  uint16_t currentTest_ = 0;
  uint16_t totalTests_ = 10;
};

}  // namespace LoraDisplayModel
