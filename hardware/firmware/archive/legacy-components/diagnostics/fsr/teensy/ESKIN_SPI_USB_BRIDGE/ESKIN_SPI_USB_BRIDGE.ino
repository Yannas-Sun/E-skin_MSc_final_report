/*
 * E-SKIN Teensy 4.1 SPI-to-USB bridge
 *
 * Teensy is the SPI master. STM32 is the SPI3 slave.
 * STM32 raises HOST_IRQ when a complete 16x16 frame is ready.
 * The Teensy clocks one 515-byte frame and writes the validated frame
 * to the USB serial interface as binary data.
 */

#include <Arduino.h>
#include <SPI.h>

constexpr uint8_t STM32_CS_PIN = 10;   // Teensy -> STM32 PA15 / SPI3_NSS
constexpr uint8_t STM32_IRQ_PIN = 2;  // STM32 PB8 -> Teensy interrupt input
constexpr uint32_t USB_BAUD = 2000000;
constexpr uint32_t SPI_HZ = 100000;  // validated bring-up speed
constexpr uint32_t IRQ_RELEASE_TIMEOUT_MS = 1500;
constexpr size_t FRAME_BYTES = 1 + 2 + (16 * 16 * 2);
constexpr uint8_t FRAME_MAGIC = 0xA5;

uint8_t spiRx[FRAME_BYTES];
uint32_t droppedUsbFrames = 0;

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

void setup() {
  pinMode(STM32_CS_PIN, OUTPUT);
  digitalWrite(STM32_CS_PIN, HIGH);
  // PB8/HOST_IRQ is also STM32 BOOT0; keep it weakly low during reset.
  pinMode(STM32_IRQ_PIN, INPUT_PULLDOWN);

  SPI.begin();
  Serial.begin(USB_BAUD);
  Serial.println("# ESKIN_FSR_BRIDGE_READY");
}

bool readFrame() {
  /*
   * HOST_IRQ is asserted just before the STM32 enters its blocking SPI call.
   * Retain the guard delays already validated by the isolated 0x55 test.
   */
  delayMicroseconds(1000);
  SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0));
  digitalWrite(STM32_CS_PIN, LOW);
  delayMicroseconds(1000);
  for (size_t i = 0; i < FRAME_BYTES; ++i) {
    spiRx[i] = SPI.transfer(0x00);
  }
  // Let the STM32 consume the final MOSI byte and complete its RX FIFO checks
  // before NSS rises and closes the slave transaction.
  delayMicroseconds(100);
  digitalWrite(STM32_CS_PIN, HIGH);
  SPI.endTransaction();

  if (spiRx[0] != FRAME_MAGIC) {
    Serial.print("# BAD_MAGIC 0x");
    if (spiRx[0] < 0x10U) {
      Serial.print('0');
    }
    Serial.println(spiRx[0], HEX);
    return false;
  }

  /*
   * The Teensy USB CDC buffer can report less than FRAME_BYTES of immediately
   * available space even while the PC is connected. Requiring all 515 bytes
   * to fit at once therefore drops every valid STM32 frame on some USB buffer
   * configurations. The STM32 SPI transaction is already complete here, so
   * it is safe to let Serial.write() wait while it sends this complete frame.
   */
  if (Serial) {
    const size_t written = Serial.write(spiRx, FRAME_BYTES);
    if (written != FRAME_BYTES) {
      ++droppedUsbFrames;
    }
  } else {
    ++droppedUsbFrames;
  }
  return true;
}

void loop() {
  static uint32_t last_wait_report_ms = 0U;

  if (digitalRead(STM32_IRQ_PIN) == HIGH) {
    readFrame();
    // Wait for STM32 to deassert IRQ before accepting another frame.
    if (!waitForLevel(STM32_IRQ_PIN, LOW, IRQ_RELEASE_TIMEOUT_MS)) {
      Serial.println("# IRQ_RELEASE_TIMEOUT");
    }
  } else if ((millis() - last_wait_report_ms) >= 1000U) {
    /*
     * Keep the binary USB stream clean. Periodic ASCII diagnostics inserted
     * between fixed-size frames force the PC parser to lose frame alignment.
     */
    last_wait_report_ms = millis();
  }
}
