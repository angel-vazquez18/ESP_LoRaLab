#include "board_bench.h"

#if defined(AUDIO_BOARD_HELTEC_V4) && AUDIO_BOARD_HELTEC_V4

#include <Arduino.h>
#include <SSD1306Wire.h>
#include <Wire.h>
#include <esp_mac.h>

namespace {

constexpr uint8_t OLED_ADDRESS = 0x3c;
constexpr int OLED_SDA = 17;
constexpr int OLED_SCL = 18;
constexpr int OLED_RESET = 21;
constexpr int VEXT_CONTROL = 36;  // Standard V4/S3R2 only; active low.
constexpr int RADIO_NSS = 8;
constexpr int RADIO_RESET = 12;
constexpr int FEM_ENABLE = 2;
constexpr int FEM_TX_CONTROL = 5;

#ifndef BENCH_NODE_ID
#define BENCH_NODE_ID 0
#endif

#if BENCH_NODE_ID == 6
constexpr const char* NODE_LABEL = "Heltec-A / COM6";
#elif BENCH_NODE_ID == 7
constexpr const char* NODE_LABEL = "Heltec-B / COM7";
#else
constexpr const char* NODE_LABEL = "Heltec V4 / unassigned";
#endif

// Wire is explicitly initialized below. The -1 arguments keep the display
// driver from reinitializing it on the variant's default SDA3/SCL4 pins.
SSD1306Wire display(OLED_ADDRESS, -1, -1, GEOMETRY_128_64, I2C_ONE, -1);
bool beginCalled = false;
bool oledReady = false;
char baseMac[18] = "unknown";
char macSuffix[9] = "unknown";

void readIdentity() {
  uint8_t mac[6] = {};
  if (esp_efuse_mac_get_default(mac) != ESP_OK) return;
  snprintf(baseMac, sizeof(baseMac), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  snprintf(macSuffix, sizeof(macSuffix), "%02X:%02X:%02X",
           mac[3], mac[4], mac[5]);
}

void output(int pin, int level) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, level);
}

}  // namespace

namespace BoardBench {

void begin() {
  if (beginCalled) return;
  beginCalled = true;
  readIdentity();

  // Audio bring-up does not initialize or transmit through the SX1262.
  // Hold it in reset, deselect SPI, and disable the V4.3 RF front end.
  output(RADIO_RESET, LOW);
  output(RADIO_NSS, HIGH);
  output(FEM_ENABLE, LOW);
  output(FEM_TX_CONTROL, LOW);

  // Vext supplies the onboard OLED. Do not initialize the GNSS interface:
  // GPIO38-41 belong to the external audio/PTT wiring in this bench.
  output(VEXT_CONTROL, LOW);
  delay(50);
  output(OLED_RESET, LOW);
  delay(10);
  digitalWrite(OLED_RESET, HIGH);
  delay(20);

  if (!Wire.begin(OLED_SDA, OLED_SCL, 400000)) {
    Serial.println("[OLED] I2C initialization failed; serial bench remains available");
    return;
  }
  Wire.setTimeOut(50);
  Wire.beginTransmission(OLED_ADDRESS);
  const uint8_t probeResult = Wire.endTransmission();
  if (probeResult != 0) {
    Serial.printf("[OLED] No ACK at 0x3C (I2C error %u); serial bench remains available\n",
                  static_cast<unsigned>(probeResult));
    return;
  }
  // The driver's init result alone is not proof of a connected OLED; the
  // separate ACK probe above distinguishes an absent display from success.
  if (!display.init()) {
    Serial.println("[OLED] Display initialization failed; serial bench remains available");
    return;
  }
  oledReady = true;
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);
  display.setContrast(128);
  showStatus("Initializing audio", false, false);
  Serial.println("[OLED] ACK received at 0x3C; node label written");
}

void printIdentity() {
  readIdentity();
  Serial.printf("[BOARD] %s | Heltec WiFi LoRa 32 V4.3 / ESP32-S3R2 profile\n",
                NODE_LABEL);
  Serial.printf("[BOARD] Base MAC: %s | chip: %s rev %u | flash: %lu bytes | PSRAM: %lu bytes\n",
                baseMac, ESP.getChipModel(), static_cast<unsigned>(ESP.getChipRevision()),
                static_cast<unsigned long>(ESP.getFlashChipSize()),
                static_cast<unsigned long>(ESP.getPsramSize()));
  Serial.printf("[BOARD] OLED ACK/init=%u | radio held in reset, FEM disabled | PTT disabled\n",
                oledReady ? 1U : 0U);
  Serial.println("[BOARD] COM label is the assigned bench port; Windows may reassign it");
}

void showStatus(const char* status, bool microphoneReady, bool speakerReady) {
  if (!oledReady) return;
  display.clear();
  display.drawString(0, 0, NODE_LABEL);
  display.drawString(0, 15, String("MAC ") + macSuffix);
  display.drawString(0, 30, status != nullptr ? status : "");
  char readiness[24];
  snprintf(readiness, sizeof(readiness), "MIC %s  SPK %s",
           microphoneReady ? "OK" : "--", speakerReady ? "OK" : "--");
  display.drawString(0, 45, readiness);
  display.display();
}

}  // namespace BoardBench

#else

namespace BoardBench {
void begin() {}
void printIdentity() {}
void showStatus(const char*, bool, bool) {}
}  // namespace BoardBench

#endif
