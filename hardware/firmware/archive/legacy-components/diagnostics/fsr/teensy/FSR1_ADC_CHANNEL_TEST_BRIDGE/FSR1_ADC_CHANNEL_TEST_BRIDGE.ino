/*
 * E-SKIN FSR1 AIN10 live monitor.
 *
 * STM32 steps MUX1 through channels 0..15 once per second and reads only
 * MAX11633 AIN10. Teensy clocks one compact SPI frame and prints the decoded
 * result directly to the USB Serial Monitor. No CSV or binary file is needed.
 */

#include <Arduino.h>
#include <SPI.h>

constexpr uint8_t STM32_CS_PIN = 10;
constexpr uint8_t STM32_IRQ_PIN = 2;
constexpr uint32_t USB_BAUD = 2000000;
constexpr uint32_t SPI_HZ = 100000;
constexpr uint32_t IRQ_RELEASE_TIMEOUT_MS = 1500;
constexpr float ADC_REFERENCE_V = 3.3f;

constexpr uint8_t FRAME_MAGIC = 0xA7;
constexpr uint8_t EXPECTED_AIN = 10;
constexpr size_t FRAME_BYTES = 8;

uint8_t spiRx[FRAME_BYTES];
uint32_t validFrames = 0;
uint32_t invalidFrames = 0;

bool waitForLevel(uint8_t pin, uint8_t level, uint32_t timeout_ms) {
  const uint32_t start = millis();
  while (digitalRead(pin) != level) {
    if ((millis() - start) >= timeout_ms) {
      return false;
    }
    yield();
  }
  return true;
}

bool readLiveFrame() {
  delayMicroseconds(1000);
  SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0));
  digitalWrite(STM32_CS_PIN, LOW);
  delayMicroseconds(1000);

  for (size_t index = 0; index < FRAME_BYTES; ++index) {
    spiRx[index] = SPI.transfer(0x00);
  }

  delayMicroseconds(100);
  digitalWrite(STM32_CS_PIN, HIGH);
  SPI.endTransaction();

  uint8_t checksum = 0;
  for (size_t index = 0; index < FRAME_BYTES - 1; ++index) {
    checksum ^= spiRx[index];
  }

  if (spiRx[0] != FRAME_MAGIC ||
      spiRx[3] >= 16 ||
      spiRx[4] != EXPECTED_AIN ||
      checksum != spiRx[7]) {
    ++invalidFrames;
    if (Serial) {
      Serial.print("FRAME ERROR  magic=0x");
      Serial.print(spiRx[0], HEX);
      Serial.print(" mux=");
      Serial.print(spiRx[3]);
      Serial.print(" ain=");
      Serial.print(spiRx[4]);
      Serial.print(" checksum=0x");
      Serial.print(spiRx[7], HEX);
      Serial.print(" expected=0x");
      Serial.println(checksum, HEX);
    }
    return false;
  }

  const uint16_t sequence =
      static_cast<uint16_t>(spiRx[1]) |
      (static_cast<uint16_t>(spiRx[2]) << 8);
  const uint8_t mux = spiRx[3];
  const uint16_t adc =
      (static_cast<uint16_t>(spiRx[5]) |
       (static_cast<uint16_t>(spiRx[6]) << 8)) &
      0x0FFF;
  const float voltage = static_cast<float>(adc) * ADC_REFERENCE_V / 4095.0f;

  ++validFrames;
  if (Serial) {
    Serial.print("seq=");
    Serial.print(sequence);
    Serial.print("  MUX=");
    Serial.print(mux);
    Serial.print(" (position ");
    Serial.print(mux + 1);
    Serial.print("/16)  AIN10  ADC=");
    Serial.print(adc);
    Serial.print("/4095  V=");
    Serial.print(voltage, 4);
    Serial.print("  valid=");
    Serial.print(validFrames);
    Serial.print("  errors=");
    Serial.println(invalidFrames);
  }
  return true;
}

void setup() {
  pinMode(STM32_CS_PIN, OUTPUT);
  digitalWrite(STM32_CS_PIN, HIGH);
  pinMode(STM32_IRQ_PIN, INPUT_PULLDOWN);
  SPI.begin();
  Serial.begin(USB_BAUD);
  while (!Serial && millis() < 3000) {
    yield();
  }
  Serial.println();
  Serial.println("E-SKIN live monitor: MUX1 0..15, one step/s, AIN10 only");
  Serial.println("Waiting for STM32 HOST_IRQ...");
}

void loop() {
  if (digitalRead(STM32_IRQ_PIN) == HIGH) {
    readLiveFrame();
    if (!waitForLevel(STM32_IRQ_PIN, LOW, IRQ_RELEASE_TIMEOUT_MS) && Serial) {
      Serial.println("IRQ TIMEOUT: STM32 did not release HOST_IRQ");
    }
  }
}
