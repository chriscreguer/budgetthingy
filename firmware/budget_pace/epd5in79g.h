/*
 * epd5in79g.h - Minimal Arduino driver for the Waveshare 5.79" e-Paper (G) panel.
 *
 * 792 x 272, 4-color (Black/White/Yellow/Red), SPI Mode 0.
 * Ported from Waveshare's reference driver:
 *   e-Paper/RaspberryPi_JetsonNano/c/lib/e-Paper/EPD_5in79g.c (V1.0, 2023-07-04)
 *
 * This driver does NOT do any graphics/font rendering. It only pushes a
 * pre-rendered, 2-bit-packed framebuffer (EPD_BUFFER_SIZE bytes) produced by
 * convert_image.py. All panel-specific dual-controller / mirrored streaming
 * happens inside EPD_Display().
 *
 * Pin assignments are fixed by the Waveshare Universal e-Paper ESP32 Driver
 * Board PCB and are defined in epd5in79g.cpp.
 */
#ifndef EPD5IN79G_H
#define EPD5IN79G_H

#include <Arduino.h>

#define EPD_WIDTH        792
#define EPD_HEIGHT       272
// (792 / 4 pixels-per-byte) * 272 rows = 53,856 bytes
#define EPD_BUFFER_SIZE  ((EPD_WIDTH / 4) * EPD_HEIGHT)

// 2-bit color codes (match convert_image.py COLOR_MAP)
#define EPD_BLACK   0x0
#define EPD_WHITE   0x1
#define EPD_YELLOW  0x2
#define EPD_RED     0x3

void EPD_Init();                         // Reset + power on + load LUT
void EPD_Display(const uint8_t *image);  // Push EPD_BUFFER_SIZE bytes, refresh, wait BUSY
void EPD_Sleep();                        // Deep-sleep the panel (REQUIRED before MCU sleep)
void EPD_Clear();                        // White out the screen

#endif  // EPD5IN79G_H
