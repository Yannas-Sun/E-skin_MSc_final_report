#pragma once
#include "Arduino.h"
#define MSBFIRST 1
#define SPI_MODE0 0
struct SPISettings { SPISettings(uint32_t, int, int) {} };
struct MockSPI {
  std::vector<uint8_t> source, sent;
  std::vector<size_t> chunks;
  size_t offset = 0;
  bool transaction = false;
  void begin() {}
  void beginTransaction(SPISettings) { assert(!transaction); transaction = true; }
  void endTransaction() { assert(transaction && mock_cs == -1); transaction = false; }
  void transfer(void* pointer, size_t length) {
    assert(transaction && mock_cs != -1);
    assert(offset + length <= source.size());
    uint8_t* buffer = static_cast<uint8_t*>(pointer);
    sent.insert(sent.end(), buffer, buffer + length);
    memcpy(buffer, source.data() + offset, length);
    offset += length; chunks.push_back(length);
  }
  void reset(const std::vector<uint8_t>& bytes) {
    assert(!transaction && mock_cs == -1);
    source = bytes; source.resize(1044, 0); sent.clear(); chunks.clear(); offset = 0;
    mock_cs_lows = mock_cs_highs = 0;
  }
};
extern MockSPI SPI;
