#include <Arduino.h>
#include <SPI.h>

#ifndef SCALABILITY_MODULE_ID
#define SCALABILITY_MODULE_ID 0
#endif

#ifndef DATA_SCALABILITY_DEFAULT_MODE
#define DATA_SCALABILITY_DEFAULT_MODE 0
#endif

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
constexpr uint32_t SPI_HZ = 10000000U;
constexpr uint32_t USB_BAUD = 2000000U;
constexpr uint32_t IRQ_TIMEOUT_MS = 1500U;
constexpr uint32_t HOST_PERIOD_US = 5000U;
constexpr size_t HOST_SLOT_BYTES = 1188U;
constexpr size_t COMMAND_BYTES = 12U;
constexpr size_t USB_QUEUE_DEPTH = 8U;
constexpr uint8_t FLAG_CRC_PRESENT = 0x10U;

enum DataMode : uint8_t {
  MODE_FULL = 0U,
  MODE_DELTA = 1U,
  MODE_SPATIAL = 2U,
};

struct UsbPacket {
  uint8_t data[HOST_SLOT_BYTES];
  uint16_t length;
};

UsbPacket usbQueue[USB_QUEUE_DEPTH];
size_t queueHead = 0U;
size_t queueTail = 0U;
size_t queueCount = 0U;
size_t queueOffset = 0U;
uint32_t framesReceived = 0U;
uint32_t framesForwarded = 0U;
uint32_t badFrames = 0U;
uint32_t droppedFrames = 0U;
uint32_t lastHostStartUs = 0U;
uint32_t irqTimeouts = 0U;
uint8_t selectedMode = DATA_SCALABILITY_DEFAULT_MODE;
bool modeCommandPending = true;

uint8_t readU8(const uint8_t *data, size_t offset) {
  return data[offset];
}

uint16_t readU16(const uint8_t *data, size_t offset) {
  return (uint16_t)data[offset] |
         ((uint16_t)data[offset + 1U] << 8U);
}

uint32_t readU32(const uint8_t *data, size_t offset) {
  return (uint32_t)data[offset] |
         ((uint32_t)data[offset + 1U] << 8U) |
         ((uint32_t)data[offset + 2U] << 16U) |
         ((uint32_t)data[offset + 3U] << 24U);
}

uint32_t crc32Ieee(const uint8_t *data, size_t length) {
  uint32_t crc = 0xFFFFFFFFU;
  for (size_t i = 0U; i < length; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0U; bit < 8U; ++bit) {
      const uint32_t mask = 0U - (crc & 1U);
      crc = (crc >> 1U) ^ (0xEDB88320U & mask);
    }
  }
  return ~crc;
}

bool markerIs(const uint8_t *frame, char a, char b, char c, char d) {
  return frame[0] == (uint8_t)a && frame[1] == (uint8_t)b &&
         frame[2] == (uint8_t)c && frame[3] == (uint8_t)d;
}

const char *modeName(uint8_t mode) {
  if (mode == MODE_DELTA) return "DELTA";
  if (mode == MODE_SPATIAL) return "SPATIAL";
  return "FULL";
}

void setSelectedMode(uint8_t mode) {
  if (mode > MODE_SPATIAL) return;
  selectedMode = mode;
  modeCommandPending = true;
}

void buildModeCommand(uint8_t command[COMMAND_BYTES]) {
  memset(command, 0, COMMAND_BYTES);
  command[0] = 'D';
  command[1] = 'S';
  command[2] = 'C';
  command[3] = 'M';
  command[4] = 1U;
  command[5] = selectedMode;
  /* Default thresholds: Delta ADC-code change and Spatial trigger. */
  command[6] = 8U;
  command[7] = 0U;
  command[8] = 128U;
  command[9] = 0U;
}

uint8_t hostSpiTransfer(uint8_t output) {
  return SPI.transfer(output);
}

bool waitForIrq(uint32_t timeoutMs) {
  const uint32_t started = millis();
  while (digitalRead(STM32_IRQ_PIN) != HIGH) {
    if ((millis() - started) >= timeoutMs) return false;
    yield();
  }
  return true;
}

bool queueFrame(const uint8_t *frame, uint16_t length) {
  if (queueCount >= USB_QUEUE_DEPTH) {
    ++droppedFrames;
    return false;
  }
  memcpy(usbQueue[queueTail].data, frame, length);
  usbQueue[queueTail].length = length;
  queueTail = (queueTail + 1U) % USB_QUEUE_DEPTH;
  ++queueCount;
  return true;
}

bool parseLengthAndValidate(uint8_t *frame, uint16_t *length) {
  const bool eskf = markerIs(frame, 'E', 'S', 'K', 'F');
  const bool eskd = markerIs(frame, 'E', 'S', 'K', 'D');
  const bool esk0 = markerIs(frame, 'E', 'S', 'K', '0');
  const bool espf = markerIs(frame, 'E', 'S', 'P', 'F');
  const bool espd = markerIs(frame, 'E', 'S', 'P', 'D');
  const bool esp0 = markerIs(frame, 'E', 'S', 'P', '0');

  if (eskf || eskd || esk0) {
    if (frame[4] != 2U) return false;
    const uint16_t declared = readU16(frame, 6U);
    if ((declared < 164U) || (declared > HOST_SLOT_BYTES)) return false;
    if (eskf && declared != 1188U) return false;
    if (eskd) {
      const uint16_t changed = readU16(frame, 160U);
      if (declared != (uint16_t)(166U + 4U * changed)) return false;
    }
    if (esk0 && declared != 164U) return false;
    if ((frame[5] & FLAG_CRC_PRESENT) == 0U) return false;
    const uint32_t wireCrc = readU32(frame, declared - 4U);
    if (wireCrc != crc32Ieee(frame, declared - 4U)) return false;
    *length = declared;
    return true;
  }

  if (esp0) {
    *length = 12U;
    return true;
  }
  if (espf || espd) {
    const uint16_t count = readU16(frame, 140U);
    const uint32_t declared = 142U + 4U * (uint32_t)count;
    if (declared > HOST_SLOT_BYTES) return false;
    if (espf && count > 256U) return false;
    *length = (uint16_t)declared;
    return true;
  }
  return false;
}

bool readHostSlot() {
  if (!waitForIrq(IRQ_TIMEOUT_MS)) {
    ++irqTimeouts;
    return false;
  }

  uint8_t command[COMMAND_BYTES];
  buildModeCommand(command);
  SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0));
  digitalWrite(STM32_CS_PIN, LOW);
  delayMicroseconds(10U);

  uint8_t frame[HOST_SLOT_BYTES];
  for (size_t index = 0U; index < HOST_SLOT_BYTES; ++index) {
    const uint8_t output = (modeCommandPending && index < COMMAND_BYTES)
                               ? command[index]
                               : 0U;
    frame[index] = hostSpiTransfer(output);
  }
  digitalWrite(STM32_CS_PIN, HIGH);
  SPI.endTransaction();
  modeCommandPending = false;
  ++framesReceived;

  uint16_t length = 0U;
  if (!parseLengthAndValidate(frame, &length)) {
    ++badFrames;
    return false;
  }
  return queueFrame(frame, length);
}

void drainUsbQueue() {
  if (!Serial || queueCount == 0U) return;
  const int available = Serial.availableForWrite();
  if (available <= 0) return;
  const size_t remaining = usbQueue[queueHead].length - queueOffset;
  const size_t chunk = (remaining < (size_t)available)
                           ? remaining : (size_t)available;
  const size_t written = Serial.write(usbQueue[queueHead].data + queueOffset,
                                      chunk);
  if (written == 0U) return;
  queueOffset += written;
  if (queueOffset == usbQueue[queueHead].length) {
    queueOffset = 0U;
    queueHead = (queueHead + 1U) % USB_QUEUE_DEPTH;
    --queueCount;
    ++framesForwarded;
  }
}

void printStatus() {
  Serial.printf("#DSMODE mode=%s module=%u received=%lu forwarded=%lu "
                "bad=%lu dropped=%lu queue=%u irq_timeout=%lu\r\n",
                modeName(selectedMode), (unsigned)SCALABILITY_MODULE_ID,
                (unsigned long)framesReceived,
                (unsigned long)framesForwarded,
                (unsigned long)badFrames,
                (unsigned long)droppedFrames,
                (unsigned)queueCount,
                (unsigned long)irqTimeouts);
}

void pollControlCommands() {
  if (!Serial || Serial.available() == 0) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  line.toUpperCase();
  if (line == "MODE FULL" || line == "!MODE FULL") {
    setSelectedMode(MODE_FULL);
  } else if (line == "MODE DELTA" || line == "!MODE DELTA") {
    setSelectedMode(MODE_DELTA);
  } else if (line == "MODE SPATIAL" || line == "!MODE SPATIAL") {
    setSelectedMode(MODE_SPATIAL);
  } else if (line == "STATUS" || line == "!STATUS") {
    printStatus();
  }
}

void setup() {
  pinMode(STM32_CS_PIN, OUTPUT);
  digitalWrite(STM32_CS_PIN, HIGH);
  pinMode(STM32_IRQ_PIN, INPUT_PULLDOWN);
  SPI.begin();
  Serial.begin(USB_BAUD);
  Serial.setTimeout(20U);
}

void loop() {
  pollControlCommands();
  const uint32_t nowUs = micros();
  if ((digitalRead(STM32_IRQ_PIN) == HIGH) &&
      ((lastHostStartUs == 0U) ||
       ((uint32_t)(nowUs - lastHostStartUs) >= HOST_PERIOD_US))) {
    lastHostStartUs = nowUs;
    (void)readHostSlot();
  }
  drainUsbQueue();
}
