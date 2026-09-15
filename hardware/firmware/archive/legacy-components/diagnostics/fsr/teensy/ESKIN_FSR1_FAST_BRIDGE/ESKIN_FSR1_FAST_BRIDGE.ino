/* High-rate FSR1-only STM32 SPI-to-USB bridge for Teensy 4.1. */
#include <Arduino.h>
#include <SPI.h>

constexpr uint8_t STM32_CS_PIN = 10;
constexpr uint8_t STM32_IRQ_PIN = 2;
constexpr uint32_t USB_BAUD = 2000000;
constexpr uint32_t SPI_HZ = 10000000;
constexpr uint32_t IRQ_SETTLE_US = 50;
constexpr uint32_t CS_SETUP_US = 10;
constexpr uint32_t CS_HOLD_US = 10;
constexpr uint32_t IRQ_RELEASE_TIMEOUT_MS = 1500;
constexpr size_t FRAME_BYTES = 1U + 2U + (16U * 16U * 2U);
constexpr uint8_t FRAME_MAGIC = 0xA5U;

uint8_t spiRx[FRAME_BYTES];
uint16_t lastSequence = 0U;
bool sequenceSeen = false;

bool waitForLevel(uint8_t pin, uint8_t level, uint32_t timeoutMs) {
  const uint32_t started = millis();
  while (digitalReadFast(pin) != level) {
    if ((millis() - started) >= timeoutMs) return false;
    yield();
  }
  return true;
}

bool readFrame() {
  delayMicroseconds(IRQ_SETTLE_US);
  SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0));
  digitalWriteFast(STM32_CS_PIN, LOW);
  delayMicroseconds(CS_SETUP_US);
  for (size_t i = 0U; i < FRAME_BYTES; ++i) {
    spiRx[i] = SPI.transfer(0x00);
  }
  delayMicroseconds(CS_HOLD_US);
  digitalWriteFast(STM32_CS_PIN, HIGH);
  SPI.endTransaction();

  if (spiRx[0] != FRAME_MAGIC) {
    sequenceSeen = false;
    return false;
  }

  const uint16_t sequence =
      (uint16_t)spiRx[1] | ((uint16_t)spiRx[2] << 8U);
  if (sequenceSeen && sequence != (uint16_t)(lastSequence + 1U)) {
    sequenceSeen = false;
    lastSequence = sequence;
    return false;
  }
  lastSequence = sequence;
  sequenceSeen = true;

  if (Serial) {
    return Serial.write(spiRx, FRAME_BYTES) == FRAME_BYTES;
  }
  return false;
}

void setup() {
  pinMode(STM32_CS_PIN, OUTPUT);
  digitalWriteFast(STM32_CS_PIN, HIGH);
  pinMode(STM32_IRQ_PIN, INPUT_PULLDOWN);
  SPI.begin();
  Serial.begin(USB_BAUD);
}

void loop() {
  if (digitalReadFast(STM32_IRQ_PIN) == HIGH) {
    (void)readFrame();
    (void)waitForLevel(STM32_IRQ_PIN, LOW, IRQ_RELEASE_TIMEOUT_MS);
  }
}
