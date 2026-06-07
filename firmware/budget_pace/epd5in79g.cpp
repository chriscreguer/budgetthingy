/*
 * epd5in79g.cpp - Minimal Arduino driver for the Waveshare 5.79" e-Paper (G).
 *
 * Direct port of Waveshare's reference driver (EPD_5in79g.c, V1.0 2023-07-04).
 * Command bytes, init sequence, and the dual-controller streaming order are
 * reproduced verbatim so behavior matches Waveshare's tested hardware path.
 *
 * The 5.79g has two controllers. Command 0xA2 selects which one receives the
 * subsequent 0x10 image data: 0x02 = first controller (left 396px columns),
 * 0x01 = second controller (right 396px columns). EPD_Display() streams the
 * linear framebuffer in the panel's expected top/bottom mirror-interleaved
 * order; convert_image.py produces a plain row-major buffer and does no
 * reordering of its own.
 */
#include "epd5in79g.h"
#include <SPI.h>

// --- Pin map: fixed by the Waveshare Universal e-Paper ESP32 Driver Board ---
#define EPD_CS_PIN    15
#define EPD_DC_PIN    27
#define EPD_RST_PIN   26
#define EPD_BUSY_PIN  25
#define EPD_SCK_PIN   13
#define EPD_MOSI_PIN  14

static SPISettings g_spi(4000000, MSBFIRST, SPI_MODE0);  // 4 MHz, Mode 0, MSB first

// ---------------------------------------------------------------------------
// Low-level SPI helpers. CS is framed manually around every byte (DC selects
// command vs data), matching the reference driver.
// ---------------------------------------------------------------------------
static inline void spiWriteByte(uint8_t b) {
  SPI.transfer(b);
}

static void sendCommand(uint8_t reg) {
  digitalWrite(EPD_DC_PIN, LOW);
  digitalWrite(EPD_CS_PIN, LOW);
  spiWriteByte(reg);
  digitalWrite(EPD_CS_PIN, HIGH);
}

static void sendData(uint8_t data) {
  digitalWrite(EPD_CS_PIN, LOW);
  digitalWrite(EPD_DC_PIN, HIGH);
  spiWriteByte(data);
  digitalWrite(EPD_CS_PIN, HIGH);
}

// ---------------------------------------------------------------------------
// Hardware reset: high, low pulse, high.
// ---------------------------------------------------------------------------
static void reset() {
  digitalWrite(EPD_RST_PIN, HIGH);
  delay(200);
  digitalWrite(EPD_RST_PIN, LOW);
  delay(2);
  digitalWrite(EPD_RST_PIN, HIGH);
  delay(200);
}

// Wait until BUSY goes HIGH (panel ready), matching reference `while(!busy)`.
static void readBusy() {
  do {
    delay(10);
  } while (digitalRead(EPD_BUSY_PIN) == LOW);
  delay(200);
}

// Trigger a full refresh and block until it completes.
static void turnOnDisplay() {
  sendCommand(0xA2);
  sendData(0x00);

  sendCommand(0x12);
  sendData(0x00);
  readBusy();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
void EPD_Init() {
  pinMode(EPD_CS_PIN, OUTPUT);
  pinMode(EPD_DC_PIN, OUTPUT);
  pinMode(EPD_RST_PIN, OUTPUT);
  pinMode(EPD_BUSY_PIN, INPUT);
  digitalWrite(EPD_CS_PIN, HIGH);

  // MISO and hardware-CS unused: we drive CS manually as a plain GPIO.
  SPI.begin(EPD_SCK_PIN, -1, EPD_MOSI_PIN, -1);
  // Held for the whole session; the MCU resets SPI on deep-sleep wake.
  SPI.beginTransaction(g_spi);

  reset();

  sendCommand(0xA2);
  sendData(0x01);

  sendCommand(0x00);
  sendData(0x03);
  sendData(0x29);

  sendCommand(0xA2);
  sendData(0x02);

  sendCommand(0x00);
  sendData(0x07);
  sendData(0x29);

  sendCommand(0xA2);
  sendData(0x00);

  sendCommand(0x50);
  sendData(0x97);

  sendCommand(0x61);  // resolution: 0x018c=396 per controller, 0x0110=272 high
  sendData(0x01);
  sendData(0x8c);
  sendData(0x01);
  sendData(0x10);

  sendCommand(0x06);  // booster soft start
  sendData(0x38);
  sendData(0x38);
  sendData(0x38);
  sendData(0x00);

  sendCommand(0xE9);
  sendData(0x01);

  sendCommand(0xE0);
  sendData(0x01);

  sendCommand(0x04);  // power on
  readBusy();
}

void EPD_Display(const uint8_t *image) {
  // Width1: bytes per full row in the source buffer (4 px/byte) = 198
  // Width:  bytes per half row (one controller's worth, 8 px/byte) = 99
  const uint16_t Width1 = (EPD_WIDTH % 4 == 0) ? (EPD_WIDTH / 4) : (EPD_WIDTH / 4 + 1);
  const uint16_t Width  = (EPD_WIDTH % 8 == 0) ? (EPD_WIDTH / 8) : (EPD_WIDTH / 8 + 1);
  const uint16_t Height = EPD_HEIGHT;

  // Controller 0x02: left half (first `Width` bytes of each row), top/bottom
  // rows interleaved over the first half of the height.
  sendCommand(0xA2);
  sendData(0x02);
  sendCommand(0x10);
  for (uint16_t j = 0; j < Height / 2; j++) {
    for (uint16_t i = 0; i < Width; i++) {
      sendData(image[i + j * Width1]);
    }
    for (uint16_t i = 0; i < Width; i++) {
      sendData(image[i + (Height - j - 1) * Width1]);
    }
  }

  // Controller 0x01: right half (offset by `Width` bytes into each row).
  // Loop bounds reproduce the reference driver verbatim.
  sendCommand(0xA2);
  sendData(0x01);
  sendCommand(0x10);
  for (uint16_t j = 0; j < Height; j++) {
    for (uint16_t i = 0; i < Width; i++) {
      sendData(image[j * Width1 + i + Width]);
    }
    for (uint16_t i = 0; i < Width; i++) {
      sendData(image[(Height - j - 1) * Width1 + i + Width]);
    }
  }

  turnOnDisplay();
}

void EPD_Clear() {
  const uint16_t Width = (EPD_WIDTH % 8 == 0) ? (EPD_WIDTH / 8) : (EPD_WIDTH / 8 + 1);
  const uint16_t Height = EPD_HEIGHT;
  const uint8_t color = EPD_WHITE;
  const uint8_t fill = (color << 6) | (color << 4) | (color << 2) | color;

  sendCommand(0xA2);
  sendData(0x02);
  sendCommand(0x10);
  for (uint16_t j = 0; j < Height; j++) {
    for (uint16_t i = 0; i < Width; i++) {
      sendData(fill);
    }
  }

  sendCommand(0xA2);
  sendData(0x01);
  sendCommand(0x10);
  for (uint16_t j = 0; j < Height; j++) {
    for (uint16_t i = 0; i < Width; i++) {
      sendData(fill);
    }
  }

  turnOnDisplay();
}

void EPD_Sleep() {
  // Deep sleep (0x07 / 0xA5). Per Waveshare's reference the POWER_OFF (0x02)
  // step is intentionally omitted -- it is commented out in their driver.
  sendCommand(0x07);
  sendData(0xA5);
}
