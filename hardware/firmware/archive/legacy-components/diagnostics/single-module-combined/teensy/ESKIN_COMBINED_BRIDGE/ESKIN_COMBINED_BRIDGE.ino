/* E-SKIN combined FSR1 + FSR2 + 9-ACC bridge for Teensy 4.1. */
#include <Arduino.h>
#include <SPI.h>

#ifndef SCALABILITY_MODULE_ID
#define SCALABILITY_MODULE_ID 0
#endif

/*
 * The normal bridge remains Module 0.  The scalability sketch includes this
 * file with SCALABILITY_MODULE_ID set at compile time, so the same frame
 * reader and GUI protocol can be used for Modules 0..3 without duplicating
 * the acquisition code.
 */
#if SCALABILITY_MODULE_ID == 0
constexpr uint8_t STM32_CS_PIN = 10;
constexpr uint8_t STM32_IRQ_PIN = 2;
#elif SCALABILITY_MODULE_ID == 1
constexpr uint8_t STM32_CS_PIN = 14;
constexpr uint8_t STM32_IRQ_PIN = 3;
#elif SCALABILITY_MODULE_ID == 2
constexpr uint8_t STM32_CS_PIN = 15;
constexpr uint8_t STM32_IRQ_PIN = 4;
#elif SCALABILITY_MODULE_ID == 3
constexpr uint8_t STM32_CS_PIN = 16;
constexpr uint8_t STM32_IRQ_PIN = 5;
#else
#error "SCALABILITY_MODULE_ID must be 0, 1, 2 or 3"
#endif
constexpr uint8_t STM32_MOSI_PIN = 11;
constexpr uint8_t STM32_MISO_PIN = 12;
constexpr uint8_t STM32_SCK_PIN = 13;
constexpr uint32_t USB_BAUD = 2000000;
// 700 complete 1188-byte frames/s require at least 6.653 MHz on the wire.
// Use the Teensy 4.1 LPSPI peripheral at 10 MHz, leaving timing margin above
// the mathematical minimum while remaining well below the STM32G474 slave
// full-duplex limit. STM32 remains full-duplex DMA with ping-pong buffers.
constexpr uint32_t SPI_HZ = 10000000;
constexpr bool USE_SOFTWARE_SPI = false;
constexpr uint32_t TARGET_FRAME_HZ = 700;
constexpr uint32_t HOST_PERIOD_US = 1000000U / TARGET_FRAME_HZ;
constexpr uint32_t SPI_HALF_PERIOD_US = 1000000U / (2U * SPI_HZ);
constexpr uint32_t IRQ_SETTLE_US = 50;
constexpr uint32_t CS_SETUP_US = 10;
constexpr uint32_t CS_HOLD_US = 10;
constexpr uint32_t IRQ_RELEASE_TIMEOUT_MS = 1500;
constexpr uint32_t USB_WRITE_TIMEOUT_MS = 100;
constexpr uint32_t USB_CONNECTION_SETTLE_MS = 500;
constexpr size_t FRAME_BYTES = 1188;
constexpr size_t USB_QUEUE_DEPTH = 16;
constexpr size_t MAX_PREFIX_BYTES = 8;
constexpr uint8_t MAGIC[4] = {0x45, 0x53, 0x4B, 0x31};
constexpr uint8_t LEGACY_PROTOCOL_VERSION = 1;
constexpr uint8_t PERIODIC_CRC_PROTOCOL_VERSION = 2;
constexpr uint8_t FLAG_CRC_PRESENT = 0x10;
constexpr uint32_t CRC_FRAME_INTERVAL = 32;

uint8_t frame[FRAME_BYTES];
uint8_t usbQueue[USB_QUEUE_DEPTH][FRAME_BYTES];
size_t usbQueueHead = 0;
size_t usbQueueTail = 0;
size_t usbQueueCount = 0;
size_t usbQueueOffset = 0;
size_t usbQueueHighWater = 0;
uint32_t usbFramesSent = 0;

enum class FrameResult : uint8_t {
  Ok,
  BadMagic,
  BadHeader,
  BadSequence,
  BadCrc,
  UsbUnavailable,
  UsbShortWrite,
  Count
};

uint32_t resultCounts[static_cast<size_t>(FrameResult::Count)] = {};
uint32_t irqCount = 0;
uint32_t irqReleaseTimeoutCount = 0;
uint32_t lastDiagnosticMs = 0;
uint32_t lastHostStartUs = 0;
uint32_t lastWireCrc = 0;
uint32_t lastCalculatedCrc = 0;
uint32_t lastDiscardedPrefix = 0;
uint32_t crcCheckedCount = 0;
uint32_t crcSkippedCount = 0;
uint32_t lastFrameSequence = 0;
bool sequenceSeen = false;
bool lastCrcSampled = false;
bool usbConnectionSeen = false;
uint32_t usbConnectedAtMs = 0;

uint32_t readU32LE(const uint8_t *value) {
  return (uint32_t)value[0] | ((uint32_t)value[1] << 8U) |
         ((uint32_t)value[2] << 16U) | ((uint32_t)value[3] << 24U);
}

uint32_t crc32Ieee(const uint8_t *data, size_t length) {
  uint32_t crc = 0xFFFFFFFFU;
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      const uint32_t mask = 0U - (crc & 1U);
      crc = (crc >> 1U) ^ (0xEDB88320U & mask);
    }
  }
  return ~crc;
}

bool waitForLevel(uint8_t pin, uint8_t level, uint32_t timeoutMs) {
  const uint32_t start = millis();
  while (digitalRead(pin) != level) {
    if ((millis() - start) >= timeoutMs) return false;
    yield();
  }
  return true;
}

uint8_t hostSpiTransfer(uint8_t output) {
  if (!USE_SOFTWARE_SPI) return SPI.transfer(output);

  uint8_t input = 0;
  for (uint8_t mask = 0x80; mask != 0; mask >>= 1U) {
    digitalWriteFast(STM32_MOSI_PIN, (output & mask) ? HIGH : LOW);
    delayMicroseconds(SPI_HALF_PERIOD_US);
    digitalWriteFast(STM32_SCK_PIN, HIGH);
    if (digitalReadFast(STM32_MISO_PIN)) input |= mask;
    delayMicroseconds(SPI_HALF_PERIOD_US);
    digitalWriteFast(STM32_SCK_PIN, LOW);
  }
  return input;
}

FrameResult readCombinedFrame() {
  delayMicroseconds(IRQ_SETTLE_US);
  if (!USE_SOFTWARE_SPI) {
    SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0));
  }
  digitalWrite(STM32_CS_PIN, LOW);
  delayMicroseconds(CS_SETUP_US);

  /*
   * Search for ESK1 inside the first few clocks without releasing nCS. If the
   * STM32 peripheral exposed stale FIFO bytes first, discard only that prefix
   * and then clock the entire 1188-byte logical frame in the same transaction.
   */
  size_t clocks = 0;
  size_t matched = 0;
  while (matched < sizeof(MAGIC) && clocks < MAX_PREFIX_BYTES) {
    const uint8_t value = hostSpiTransfer(0x00);
    ++clocks;
    if (value == MAGIC[matched]) {
      frame[matched++] = value;
    } else if (value == MAGIC[0]) {
      frame[0] = value;
      matched = 1;
    } else {
      matched = 0;
    }
  }

  if (matched == sizeof(MAGIC)) {
    lastDiscardedPrefix = clocks - sizeof(MAGIC);
    for (size_t i = sizeof(MAGIC); i < FRAME_BYTES; ++i) {
      frame[i] = hostSpiTransfer(0x00);
    }
  } else {
    lastDiscardedPrefix = clocks;
    while (clocks < FRAME_BYTES) {
      (void)hostSpiTransfer(0x00);
      ++clocks;
    }
  }
  delayMicroseconds(CS_HOLD_US);
  digitalWrite(STM32_CS_PIN, HIGH);
  if (!USE_SOFTWARE_SPI) SPI.endTransaction();

  if (matched != sizeof(MAGIC)) {
    sequenceSeen = false;
    return FrameResult::BadMagic;
  }
  const uint16_t declared = (uint16_t)frame[6] | ((uint16_t)frame[7] << 8U);
  const uint8_t version = frame[4];
  if (((version != LEGACY_PROTOCOL_VERSION) &&
       (version != PERIODIC_CRC_PROTOCOL_VERSION)) ||
      declared != FRAME_BYTES) {
    sequenceSeen = false;
    return FrameResult::BadHeader;
  }
  const uint32_t frameSequence = readU32LE(&frame[8]);
  const bool crcPresent = (version == LEGACY_PROTOCOL_VERSION) ||
                          ((frame[5] & FLAG_CRC_PRESENT) != 0U);
  if ((version == PERIODIC_CRC_PROTOCOL_VERSION) &&
      (crcPresent != ((frameSequence % CRC_FRAME_INTERVAL) == 0U))) {
    sequenceSeen = false;
    return FrameResult::BadHeader;
  }
  lastCrcSampled = crcPresent;
  if (crcPresent) {
    lastWireCrc = readU32LE(&frame[FRAME_BYTES - 4U]);
    lastCalculatedCrc = crc32Ieee(frame, FRAME_BYTES - 4U);
    ++crcCheckedCount;
    if (lastCalculatedCrc != lastWireCrc) {
      sequenceSeen = false;
      return FrameResult::BadCrc;
    }
  } else {
    lastWireCrc = 0U;
    lastCalculatedCrc = 0U;
    ++crcSkippedCount;
    if (readU32LE(&frame[FRAME_BYTES - 4U]) != 0U) {
      sequenceSeen = false;
      return FrameResult::BadHeader;
    }
  }

  if (sequenceSeen && (frameSequence != (lastFrameSequence + 1U))) {
    lastFrameSequence = frameSequence;
    return FrameResult::BadSequence;
  }
  lastFrameSequence = frameSequence;
  sequenceSeen = true;

  if (!Serial) {
    usbConnectionSeen = false;
    return FrameResult::UsbUnavailable;
  }
  if (!usbConnectionSeen) {
    usbConnectionSeen = true;
    usbConnectedAtMs = millis();
    return FrameResult::UsbUnavailable;
  }
  if ((millis() - usbConnectedAtMs) < USB_CONNECTION_SETTLE_MS) {
    return FrameResult::UsbUnavailable;
  }
  /* Do not block the next STM32 transaction on USB endpoint scheduling.
   * Queue the complete CRC-valid frame and let loop() drain it only when the
   * Teensy USB stack reports available space. */
  if (usbQueueCount >= USB_QUEUE_DEPTH) return FrameResult::UsbShortWrite;
  memcpy(usbQueue[usbQueueTail], frame, FRAME_BYTES);
  usbQueueTail = (usbQueueTail + 1U) % USB_QUEUE_DEPTH;
  ++usbQueueCount;
  if (usbQueueCount > usbQueueHighWater) usbQueueHighWater = usbQueueCount;
  return FrameResult::Ok;
}

void drainUsbQueue() {
  if (!Serial) return;
  while (usbQueueCount > 0U) {
    const int available = Serial.availableForWrite();
    if (available <= 0) return;
    const size_t remaining = FRAME_BYTES - usbQueueOffset;
    const size_t chunk = (remaining < (size_t)available)
                           ? remaining : (size_t)available;
    const size_t written = Serial.write(
        usbQueue[usbQueueHead] + usbQueueOffset, chunk);
    if (written == 0U) return;
    usbQueueOffset += written;
    if (usbQueueOffset == FRAME_BYTES) {
      usbQueueOffset = 0U;
      usbQueueHead = (usbQueueHead + 1U) % USB_QUEUE_DEPTH;
      --usbQueueCount;
      ++usbFramesSent;
    }
  }
}

void printDiagnostics() {
  const uint32_t now = millis();
  if (!Serial || (now - lastDiagnosticMs) < 1000U) return;
  lastDiagnosticMs = now;
  Serial.printf(
      "#ESKDBG ms=%lu irq=%lu ok=%lu magic=%lu header=%lu sequence=%lu crc=%lu "
      "usb_off=%lu usb_short=%lu release_timeout=%lu irq_level=%u "
      "usb_sent=%lu queue=%u queue_high=%u crc_checked=%lu crc_skipped=%lu\r\n",
      (unsigned long)now,
      (unsigned long)irqCount,
      (unsigned long)resultCounts[static_cast<size_t>(FrameResult::Ok)],
      (unsigned long)resultCounts[static_cast<size_t>(FrameResult::BadMagic)],
      (unsigned long)resultCounts[static_cast<size_t>(FrameResult::BadHeader)],
      (unsigned long)resultCounts[static_cast<size_t>(FrameResult::BadSequence)],
      (unsigned long)resultCounts[static_cast<size_t>(FrameResult::BadCrc)],
      (unsigned long)resultCounts[static_cast<size_t>(FrameResult::UsbUnavailable)],
      (unsigned long)resultCounts[static_cast<size_t>(FrameResult::UsbShortWrite)],
      (unsigned long)irqReleaseTimeoutCount,
      digitalRead(STM32_IRQ_PIN) == HIGH ? 1U : 0U,
      (unsigned long)usbFramesSent,
      (unsigned int)usbQueueCount,
      (unsigned int)usbQueueHighWater,
      (unsigned long)crcCheckedCount,
      (unsigned long)crcSkippedCount);
  Serial.printf(
      "#ESKFIRST %02X %02X %02X %02X %02X %02X %02X %02X "
      "%02X %02X %02X %02X %02X %02X %02X %02X\r\n",
      frame[0], frame[1], frame[2], frame[3],
      frame[4], frame[5], frame[6], frame[7],
      frame[8], frame[9], frame[10], frame[11],
      frame[12], frame[13], frame[14], frame[15]);
  Serial.printf("#ESKCRC wire=%08lX calc=%08lX spi_hz=%lu soft_spi=%u "
                "sampled=%u\r\n",
                 (unsigned long)lastWireCrc,
                 (unsigned long)lastCalculatedCrc,
                 (unsigned long)SPI_HZ,
                 USE_SOFTWARE_SPI ? 1U : 0U,
                 lastCrcSampled ? 1U : 0U);
  Serial.printf("#ESKALIGN discarded_prefix=%lu\r\n",
                (unsigned long)lastDiscardedPrefix);
}

void setup() {
  pinMode(STM32_CS_PIN, OUTPUT);
  digitalWrite(STM32_CS_PIN, HIGH);
  pinMode(STM32_IRQ_PIN, INPUT_PULLDOWN);
  if (USE_SOFTWARE_SPI) {
    pinMode(STM32_MOSI_PIN, OUTPUT);
    pinMode(STM32_MISO_PIN, INPUT);
    pinMode(STM32_SCK_PIN, OUTPUT);
    digitalWriteFast(STM32_MOSI_PIN, LOW);
    digitalWriteFast(STM32_SCK_PIN, LOW);
  } else {
    SPI.begin();
  }
  Serial.begin(USB_BAUD);
}

void loop() {
  const uint32_t nowUs = micros();
  if ((digitalRead(STM32_IRQ_PIN) == HIGH) &&
      ((lastHostStartUs == 0U) ||
       ((uint32_t)(nowUs - lastHostStartUs) >= HOST_PERIOD_US))) {
    lastHostStartUs = nowUs;
    ++irqCount;
    const FrameResult result = readCombinedFrame();
    ++resultCounts[static_cast<size_t>(result)];
    if (!waitForLevel(STM32_IRQ_PIN, LOW, IRQ_RELEASE_TIMEOUT_MS)) {
      ++irqReleaseTimeoutCount;
    }
  }
  drainUsbQueue();
  printDiagnostics();
}
