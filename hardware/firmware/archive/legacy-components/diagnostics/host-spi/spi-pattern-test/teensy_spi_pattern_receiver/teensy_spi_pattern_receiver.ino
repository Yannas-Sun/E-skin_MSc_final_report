#include <Arduino.h>
#include <SPI.h>

constexpr uint8_t HOST_IRQ_PIN = 2;
constexpr uint8_t HOST_CS_PIN = 10;
constexpr uint32_t SPI_CLOCK_HZ = 100000U;
constexpr uint32_t IRQ_TIMEOUT_MS = 1500U;
constexpr uint8_t EXPECTED_BYTE = 0x55U;

static bool waitForLevel(uint8_t pin, uint8_t level, uint32_t timeout_ms) {
  const uint32_t start = millis();
  while (digitalRead(pin) != level) {
    if ((millis() - start) >= timeout_ms) {
      return false;
    }
  }
  return true;
}

static void printBits(uint8_t value) {
  for (int bit = 7; bit >= 0; --bit) {
    Serial.print((value >> bit) & 0x01U);
  }
}

void setup() {
  /*
   * PB8/HOST_IRQ is also STM32 BOOT0. A weak Teensy pull-down helps keep the
   * line defined during an STM32 reset; an external 10 kOhm pull-down is still
   * recommended for reliable simultaneous power-up.
   */
  pinMode(HOST_IRQ_PIN, INPUT_PULLDOWN);

  pinMode(HOST_CS_PIN, OUTPUT);
  digitalWrite(HOST_CS_PIN, HIGH);

  SPI.begin();

  Serial.begin(115200);
  while (!Serial && millis() < 2000U) {}

  Serial.println("Teensy SPI pattern receiver: expecting STM32 0x55");
}

void loop() {
  if (!waitForLevel(HOST_IRQ_PIN, HIGH, IRQ_TIMEOUT_MS)) {
    Serial.println("IRQ timeout: STM32 is not ready");
    delay(100);
    return;
  }

  SPI.beginTransaction(SPISettings(SPI_CLOCK_HZ, MSBFIRST, SPI_MODE0));
  delayMicroseconds(1000);
  digitalWrite(HOST_CS_PIN, LOW);
  delayMicroseconds(1000);
  const uint8_t received = SPI.transfer(0x00U);
  delayMicroseconds(1000);
  digitalWrite(HOST_CS_PIN, HIGH);
  SPI.endTransaction();

  Serial.print("RX: 0x");
  if (received < 0x10U) {
    Serial.print('0');
  }
  Serial.print(received, HEX);
  Serial.print("  bits=");
  printBits(received);
  Serial.print("  ");
  Serial.println(received == EXPECTED_BYTE ? "PASS" : "FAIL");

  /*
   * Do not start another transaction until the STM32 has completed the current
   * HAL call and lowered HOST_IRQ.
   */
  if (!waitForLevel(HOST_IRQ_PIN, LOW, IRQ_TIMEOUT_MS)) {
    Serial.println("IRQ release timeout");
  }
  delay(100);
}
