#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>
#include <vector>
#include <string>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT_PULLDOWN 2
extern uint32_t mock_ms;
extern int mock_cs, mock_cs_lows, mock_cs_highs;
extern uint8_t mock_pin_levels[256];
inline uint32_t millis() { return mock_ms; }
inline void yield() { ++mock_ms; }
inline void delayMicroseconds(uint32_t) {}
inline void pinMode(uint8_t, int) {}
inline int digitalRead(uint8_t pin) { return mock_pin_levels[pin]; }
inline void digitalWrite(uint8_t pin, uint8_t value) {
  if (pin != 10 && pin != 14 && pin != 15 && pin != 16) return;
  if (value == LOW) { assert(mock_cs == -1); mock_cs = pin; ++mock_cs_lows; }
  else { assert(mock_cs == pin || mock_cs == -1); mock_cs = -1; ++mock_cs_highs; }
}
struct MockSerial {
  std::vector<uint8_t> written;
  std::string input;
  size_t position = 0;
  void begin(uint32_t) {}
  int availableForWrite() { return 4096; }
  size_t write(const uint8_t* data, size_t size) { written.insert(written.end(), data, data + size); return size; }
  int available() { return (int)(input.size() - position); }
  int read() { return position < input.size() ? input[position++] : -1; }
};
extern MockSerial Serial;
