/*
 * budget_pace.ino - Budget Pace e-paper display, ESP32 firmware.
 *
 * On each wake: connect WiFi, GET a pre-rendered 53,856-byte .bin from the
 * server, push it to the 5.79" (G) panel, then deep-sleep for SLEEP_HOURS.
 * All rendering happens server-side (budget_pace.py + convert_image.py); this
 * sketch only transports and displays the bytes.
 *
 * loop() is empty: deep sleep restarts execution from setup() on wake.
 *
 * Libraries: built-in arduino-esp32 only (WiFi, HTTPClient, SPI, esp_sleep).
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <esp_sleep.h>

#include "epd5in79g.h"

// --- Config -----------------------------------------------------------------
#define WIFI_SSID      "Costanza"
#define WIFI_PASSWORD  "serenitynow"
#define IMAGE_URL      "https://budgetthingy.vercel.app/api/display"
#define SLEEP_HOURS    24
// ----------------------------------------------------------------------------

static const size_t   EXPECTED_SIZE   = EPD_BUFFER_SIZE;  // 53,856
static const uint32_t WIFI_TIMEOUT_MS = 30000;
static const uint32_t HTTP_READ_TIMEOUT_MS = 30000;

// Disconnect radios and deep-sleep. Never returns.
static void goToSleep() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  const uint64_t us = (uint64_t)SLEEP_HOURS * 3600ULL * 1000000ULL;
  Serial.printf("Sleeping for %d hours...\n", SLEEP_HOURS);
  Serial.flush();

  esp_sleep_enable_timer_wakeup(us);
  esp_deep_sleep_start();
}

// Connect to WiFi with a timeout. Returns true on success.
static bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("WiFi connecting");
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < WIFI_TIMEOUT_MS) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("ERROR: WiFi connect timed out.");
    return false;
  }
  Serial.print("WiFi OK, IP: ");
  Serial.println(WiFi.localIP());
  return true;
}

// GET IMAGE_URL into `buffer`. Requires exactly EXPECTED_SIZE bytes.
// Returns true only if the full frame was received.
static bool fetchImage(uint8_t *buffer) {
  HTTPClient http;
  http.begin(IMAGE_URL);

  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("ERROR: HTTP GET returned %d\n", code);
    http.end();
    return false;
  }

  const int len = http.getSize();
  Serial.printf("HTTP OK, content-length: %d\n", len);
  if (len != (int)EXPECTED_SIZE) {
    Serial.printf("ERROR: expected %u bytes, got %d\n", (unsigned)EXPECTED_SIZE, len);
    http.end();
    return false;
  }

  WiFiClient *stream = http.getStreamPtr();
  size_t received = 0;
  uint32_t lastProgress = millis();
  while (received < EXPECTED_SIZE) {
    const size_t avail = stream->available();
    if (avail) {
      size_t want = EXPECTED_SIZE - received;
      if (want > avail) want = avail;
      const int r = stream->readBytes(buffer + received, want);
      received += (r > 0) ? (size_t)r : 0;
      lastProgress = millis();
    } else {
      if (!http.connected()) break;
      if ((millis() - lastProgress) > HTTP_READ_TIMEOUT_MS) break;
      delay(1);
    }
  }
  http.end();

  if (received != EXPECTED_SIZE) {
    Serial.printf("ERROR: read %u of %u bytes\n",
                  (unsigned)received, (unsigned)EXPECTED_SIZE);
    return false;
  }
  Serial.println("Image downloaded.");
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println();
  Serial.println("=== Budget Pace: wake ===");

  // Heap allocation -- 53 KB is too large for the stack.
  uint8_t *buffer = (uint8_t *)malloc(EXPECTED_SIZE);
  if (buffer == nullptr) {
    Serial.println("ERROR: malloc failed.");
    goToSleep();  // never returns
  }

  if (connectWiFi() && fetchImage(buffer)) {
    Serial.println("Refreshing display...");
    EPD_Init();
    EPD_Display(buffer);
    EPD_Sleep();  // CRITICAL: panel into deep sleep before the MCU sleeps
    Serial.println("Display updated.");
  } else {
    Serial.println("Update skipped; will retry next wake.");
  }

  free(buffer);
  goToSleep();  // never returns
}

void loop() {
  // Empty: deep sleep restarts from setup() on wake.
}
