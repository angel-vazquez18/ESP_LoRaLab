#include "lora_bench_display.h"

#include <Arduino.h>
#include <SSD1306Wire.h>
#include <Wire.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {

constexpr uint8_t OLED_ADDRESS = 0x3C;
constexpr int OLED_SDA = 17;
constexpr int OLED_SCL = 18;
constexpr int OLED_RESET = 21;
constexpr int VEXT_CONTROL = 36;  // Standard Heltec V4/S3R2, active low.
constexpr uint32_t TASK_STACK_BYTES = 4096;
constexpr uint32_t REFRESH_MS = 100;
constexpr int FONT_HEIGHT = 13;  // ArialMT_Plain_10's actual font-cell height.
static_assert(LoraDisplayModel::ROW_Y[LoraDisplayModel::ROW_COUNT - 1] + FONT_HEIGHT <= 64,
              "Last display row must fit within 64 pixels");

// The -1 arguments preserve explicit Wire pin/clock configuration below.
SSD1306Wire display(OLED_ADDRESS, -1, -1, GEOMETRY_128_64, I2C_ONE, -1);
portMUX_TYPE modelMux = portMUX_INITIALIZER_UNLOCKED;
LoraDisplayModel::Model model;
bool started = false;
bool displayReady = false;
bool displayLayoutOk = false;
TaskHandle_t refreshTask = nullptr;

LoraDisplayModel::Model snapshot() {
  portENTER_CRITICAL(&modelMux);
  const auto copy = model;
  portEXIT_CRITICAL(&modelMux);
  return copy;
}

bool rowsFit(const LoraDisplayModel::Rows& rows) {
  for (size_t i = 0; i < LoraDisplayModel::ROW_COUNT; ++i) {
    if (display.getStringWidth(rows.text[i], static_cast<uint16_t>(strlen(rows.text[i]))) > 128) return false;
  }
  return true;
}

bool allLayoutsFit(LoraDisplayModel::Model probe) {
  // Check every state, both roles, both processing-history labels, and the
  // widest supported counter. No phase is executed by this formatting check.
  const LoraDisplayModel::State states[] = {
      LoraDisplayModel::State::Idle, LoraDisplayModel::State::Chunking,
      LoraDisplayModel::State::Transmitting, LoraDisplayModel::State::Receiving,
      LoraDisplayModel::State::Dechunking};
  const bool roles[] = {false, true};
  probe.setTest(100, 100);
  for (bool transmitter : roles) {
    probe.setRole(transmitter);
    for (auto next : states) {
      probe.setState(next);
      LoraDisplayModel::Rows rows;
      if (!probe.formatRows(rows) || !rowsFit(rows)) return false;
    }
  }
  return true;
}

void render(const LoraDisplayModel::Rows& rows) {
  display.clear();
  for (size_t i = 0; i < LoraDisplayModel::ROW_COUNT; ++i) {
    display.drawString(0, LoraDisplayModel::ROW_Y[i], rows.text[i]);
  }
  display.display();
}

void refresh(void*) {
  LoraDisplayModel::Rows previous = {};
  bool hasPrevious = false;
  TickType_t wake = xTaskGetTickCount();
  for (;;) {
    // Only a small model copy occurs under the spinlock. String work, font
    // checks, allocation and all Wire transactions stay outside it on core 0.
    const auto current = snapshot();
    LoraDisplayModel::Rows rows;
    if (!current.formatRows(rows) || !rowsFit(rows)) {
      portENTER_CRITICAL(&modelMux);
      displayLayoutOk = displayReady = false;
      portEXIT_CRITICAL(&modelMux);
    } else if (!hasPrevious || memcmp(&rows, &previous, sizeof(rows)) != 0) {
      render(rows);
      previous = rows;
      hasPrevious = true;
    }
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(REFRESH_MS));
  }
}

}  // namespace

namespace LoraBenchDisplay {

bool begin(const char* nodeLabel) {
  // Setup calls begin once before radio work. Repeated calls do not create a
  // second task, reconfigure shared I2C, or reset the user's test counter.
  if (started) return ready();
  started = true;
  auto initial = snapshot();
  if (!initial.setNodeLabel(nodeLabel)) return false;
  initial.setState(State::Idle);
  portENTER_CRITICAL(&modelMux);
  model = initial;
  portEXIT_CRITICAL(&modelMux);

  pinMode(VEXT_CONTROL, OUTPUT);
  digitalWrite(VEXT_CONTROL, LOW);
  delay(50);
  pinMode(OLED_RESET, OUTPUT);
  digitalWrite(OLED_RESET, LOW);
  delay(10);
  digitalWrite(OLED_RESET, HIGH);
  delay(20);
  if (!Wire.begin(OLED_SDA, OLED_SCL, 400000)) return false;
  Wire.setTimeOut(10);
  Wire.beginTransmission(OLED_ADDRESS);
  if (Wire.endTransmission() != 0 || !display.init()) return false;
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);
  display.setContrast(128);
  if (!allLayoutsFit(initial)) return false;
  LoraDisplayModel::Rows rows;
  if (!initial.formatRows(rows) || !rowsFit(rows)) return false;
  render(rows);  // Initial IDLE only; later refreshes belong exclusively to task.
  portENTER_CRITICAL(&modelMux);
  displayLayoutOk = true;
  portEXIT_CRITICAL(&modelMux);
  if (xTaskCreatePinnedToCore(refresh, "lora_oled", TASK_STACK_BYTES, nullptr, 1,
                             &refreshTask, 0) != pdPASS) return false;
  portENTER_CRITICAL(&modelMux);
  displayReady = true;
  portEXIT_CRITICAL(&modelMux);
  return true;
}

void setRole(bool transmitter) {
  portENTER_CRITICAL(&modelMux);
  model.setRole(transmitter);
  portEXIT_CRITICAL(&modelMux);
}

void setState(State next) {
  portENTER_CRITICAL(&modelMux);
  model.setState(next);
  portEXIT_CRITICAL(&modelMux);
}

bool setTest(uint16_t current, uint16_t total) {
  portENTER_CRITICAL(&modelMux);
  const bool accepted = model.setTest(current, total);
  portEXIT_CRITICAL(&modelMux);
  return accepted;
}

bool ready() {
  portENTER_CRITICAL(&modelMux);
  const bool value = displayReady;
  portEXIT_CRITICAL(&modelMux);
  return value;
}

bool layoutOk() {
  portENTER_CRITICAL(&modelMux);
  const bool value = displayLayoutOk;
  portEXIT_CRITICAL(&modelMux);
  return value;
}

const char* stateName(State value) { return LoraDisplayModel::stateName(value); }
State state() { return snapshot().state(); }
uint16_t currentTest() { return snapshot().currentTest(); }
uint16_t totalTests() { return snapshot().totalTests(); }

}  // namespace LoraBenchDisplay
