#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "lora_display_model.h"

using LoraDisplayModel::Model;
using LoraDisplayModel::Rows;
using LoraDisplayModel::State;

static Rows rowsOf(const Model& model) {
  Rows rows;
  assert(model.formatRows(rows));
  for (const auto& text : rows.text) assert(strlen(text) < LoraDisplayModel::ROW_BYTES);
  return rows;
}

int main() {
  Model model;
  assert(model.state() == State::Idle && model.currentTest() == 0 && model.totalTests() == 10);
  assert(model.setNodeLabel("Heltec-A / COM6"));
  model.setRole(true);
  Rows rows = rowsOf(model);
  assert(strcmp(rows.text[0], "Heltec-A / COM6") == 0);
  assert(strcmp(rows.text[1], "Role: Transmitter") == 0);
  assert(strcmp(rows.text[2], "Status: IDLE") == 0);
  assert(strcmp(rows.text[3], "Last: --") == 0);
  assert(strcmp(rows.text[4], "Test 0 of 10") == 0);

  // Fast processing states can disappear before refresh. History records real
  // work while current status advances immediately, with no simulated hold.
  model.setState(State::Chunking);
  assert(model.state() == State::Chunking);
  model.setState(State::Transmitting);
  rows = rowsOf(model);
  assert(strcmp(rows.text[2], "Status: TRANSMITTING") == 0);
  assert(strcmp(rows.text[3], "Last: CHUNKING") == 0);
  model.setRole(false);
  model.setState(State::Dechunking);
  model.setState(State::Receiving);
  rows = rowsOf(model);
  assert(strcmp(rows.text[1], "Role: Receiver") == 0);
  assert(strcmp(rows.text[2], "Status: RECEIVING") == 0);
  assert(strcmp(rows.text[3], "Last: DECHUNKING") == 0);
  model.setState(State::Idle);
  assert(strcmp(rowsOf(model).text[3], "Last: DECHUNKING") == 0);

  // Exhaust valid totals/current counters and verify every new test resets
  // both actual state and the retained phase, without changing the node/role.
  for (uint16_t total = 1; total <= 100; ++total) {
    for (uint16_t current = 0; current <= total; ++current) {
      model.setState(State::Chunking);
      assert(model.setTest(current, total));
      assert(model.currentTest() == current && model.totalTests() == total);
      assert(model.state() == State::Idle && !model.transmitter());
      rows = rowsOf(model);
      char expected[LoraDisplayModel::ROW_BYTES];
      snprintf(expected, sizeof(expected), "Test %u of %u", current, total);
      assert(strcmp(rows.text[4], expected) == 0);
      assert(strcmp(rows.text[0], "Heltec-A / COM6") == 0);
      assert(strcmp(rows.text[3], "Last: --") == 0);
    }
  }
  model.setState(State::Dechunking);
  const Rows before = rowsOf(model);
  const uint16_t invalid[][2] = {{0, 0}, {1, 0}, {11, 10}, {0, 101}, {100, 101}, {65535, 100}, {65535, 65535}};
  for (const auto& pair : invalid) {
    assert(!model.setTest(pair[0], pair[1]));
    rows = rowsOf(model);
    assert(memcmp(&before, &rows, sizeof(rows)) == 0);
    assert(model.state() == State::Dechunking && model.currentTest() == 100 && model.totalTests() == 100);
  }

  const State states[] = {State::Idle, State::Chunking, State::Transmitting, State::Receiving, State::Dechunking};
  const char* names[] = {"IDLE", "CHUNKING", "TRANSMITTING", "RECEIVING", "DECHUNKING"};
  for (size_t i = 0; i < sizeof(states) / sizeof(states[0]); ++i) {
    assert(strcmp(LoraDisplayModel::stateName(states[i]), names[i]) == 0);
    model.setState(states[i]);
    assert(model.state() == states[i]);
    rowsOf(model);
  }
  model.setState(static_cast<State>(99));
  assert(model.state() == State::Dechunking);
  assert(strcmp(LoraDisplayModel::stateName(static_cast<State>(99)), "UNKNOWN") == 0);

  // No silent label truncation. Format output remains bounded and unchanged
  // after invalid input; pixel-width validation is performed by OLED begin().
  assert(!model.setNodeLabel(nullptr) && !model.setNodeLabel(""));
  char label[LoraDisplayModel::ROW_BYTES + 1];
  memset(label, 'A', sizeof(label));
  label[sizeof(label) - 1] = 0;
  assert(!model.setNodeLabel(label));
  assert(strcmp(rowsOf(model).text[0], "Heltec-A / COM6") == 0);
  label[LoraDisplayModel::ROW_BYTES - 1] = 0;
  assert(model.setNodeLabel(label));
  assert(strlen(rowsOf(model).text[0]) == LoraDisplayModel::ROW_BYTES - 1);
  for (size_t i = 0; i < LoraDisplayModel::ROW_COUNT; ++i) {
    assert(LoraDisplayModel::ROW_Y[i] + 13 <= 64);
    if (i) assert(LoraDisplayModel::ROW_Y[i] >= LoraDisplayModel::ROW_Y[i - 1] + 12);
  }
  puts("PASS: OLED model phases/history, roles, all test-counter boundaries, labels and five-row bounds; no RF dependencies");
}
