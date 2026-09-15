/*
 * Current four-module FSR-only bridge for Teensy 4.1.
 *
 * Wire contract: ESK protocol v4 from STM32, MUL1 protocol v2 to the PC,
 * two 16 x 16 FSR layers per module, and a fixed 1044-byte Host SPI slot.
 * Historical bridge implementations are kept outside the active entry.
 */
#include <Arduino.h>
#include <SPI.h>

constexpr uint8_t MODULE_COUNT = 4;
constexpr uint8_t ALL_MODULES_MASK = (1U << MODULE_COUNT) - 1U;
constexpr uint8_t CS_PINS[MODULE_COUNT] = {10, 14, 15, 16};
constexpr uint8_t IRQ_PINS[MODULE_COUNT] = {2, 3, 4, 5};
constexpr uint32_t USB_BAUD = 2000000;
constexpr uint32_t SPI_HZ = 10000000;
#ifndef ESKIN_DEFAULT_SCAN_HZ
#define ESKIN_DEFAULT_SCAN_HZ 200
#endif
static_assert(ESKIN_DEFAULT_SCAN_HZ >= 0 && ESKIN_DEFAULT_SCAN_HZ <= 1000,
              "ESKIN_DEFAULT_SCAN_HZ must be in the range 0..1000");
constexpr uint32_t DEFAULT_SCAN_HZ = ESKIN_DEFAULT_SCAN_HZ;
constexpr uint32_t IRQ_SETTLE_US = 50;
constexpr uint32_t CS_SETUP_US = 10;
constexpr uint32_t CS_HOLD_US = 10;
constexpr uint32_t MODE_SWITCH_DELAY_MS = 1000;
constexpr uint32_t IRQ_RELEASE_TIMEOUT_MS = 100;
constexpr uint32_t MULTI_ROUND_TIMEOUT_MS = 100;
constexpr uint32_t STATUS_PACKET_INTERVAL_MS = 500;
constexpr uint32_t MIN_MODULE_OFFLINE_TIMEOUT_MS = 100;
constexpr uint32_t MODULE_OFFLINE_PERIODS = 3;

constexpr size_t HOST_SLOT_BYTES = 1044;
constexpr size_t HOST_COMMAND_BYTES = 16;
constexpr size_t PACKET_HEADER_BYTES = 20;
constexpr size_t PACKET_TRAILER_BYTES = 4;
constexpr size_t DIAGNOSTIC_PREFIX_BYTES = 16;
constexpr uint8_t ESK_PROTOCOL_VERSION = 4U;
constexpr size_t DELTA_MASK_BYTES = 32;
constexpr size_t DELTA_MASK_TOTAL_BYTES = 2 * DELTA_MASK_BYTES;
constexpr size_t DELTA_MASK_PREFIX_BYTES = 16 + DELTA_MASK_TOTAL_BYTES;
constexpr size_t DELTA_MASK_MIN_FRAME_BYTES = DELTA_MASK_PREFIX_BYTES + 4;
constexpr size_t MAX_PACKET_BYTES = PACKET_HEADER_BYTES +
                                     MODULE_COUNT * (4 + HOST_SLOT_BYTES) +
                                     PACKET_TRAILER_BYTES;
/* Keep a short burst of complete MUL1 packets while the host drains USB.
 * A depth of two made a temporary CDC scheduling delay immediately discard
 * the packet that contained the Delta/Spatial base frame. */
constexpr size_t USB_QUEUE_DEPTH = 4;

constexpr uint8_t ESK_FULL[4] = {'E', 'S', 'K', 'F'};
constexpr uint8_t ESK_DELTA[4] = {'E', 'S', 'K', 'D'};
constexpr uint8_t ESP_FULL[4] = {'E', 'S', 'P', 'F'};
constexpr uint8_t ESP_DELTA[4] = {'E', 'S', 'P', 'D'};
constexpr uint8_t ESP_HEARTBEAT[4] = {'E', 'S', 'P', '0'};
constexpr uint8_t MUL_MAGIC[4] = {'M', 'U', 'L', '1'};
constexpr uint8_t COMMAND_MAGIC[4] = {'D', 'S', 'C', 'M'};
constexpr uint8_t COMMAND_FLAG_DELTA_RESYNC = 0x01U;
constexpr uint8_t COMMAND_FLAG_SPATIAL_RESYNC = 0x02U;
constexpr uint8_t MODULE_STATUS_NOT_UPDATED = 0x80U;

enum class Algorithm : uint8_t { Full = 0, Delta = 1, Spatial = 2 };
enum class ReadResult : uint8_t {
  Ok = 0,
  BadFrame,
  BadCrc,
  NoIrq,
  Timeout,
  ModeTransition,
  ResyncNeeded,
  BadVersion,
};

struct ModuleState {
  bool haveFrame = false;
  uint16_t logicalLength = 0;
  uint32_t lastSequence = 0;
  bool sequenceSeen = false;
  uint32_t lastIrqMs = 0;
  uint32_t irqCount = 0;
  uint32_t okCount = 0;
  uint32_t badFrameCount = 0;
  uint32_t crcErrorCount = 0;
  uint32_t sequenceGapCount = 0;
  uint32_t releaseTimeoutCount = 0;
  Algorithm frameAlgorithm = Algorithm::Full;
  ReadResult lastResult = ReadResult::NoIrq;
};

uint8_t moduleFrames[MODULE_COUNT][HOST_SLOT_BYTES] = {};
ModuleState modules[MODULE_COUNT] = {};
uint8_t usbQueue[USB_QUEUE_DEPTH][MAX_PACKET_BYTES] = {};
uint16_t usbQueueLength[USB_QUEUE_DEPTH] = {};
size_t usbQueueHead = 0;
size_t usbQueueTail = 0;
size_t usbQueueCount = 0;
size_t usbQueueOffset = 0;
size_t usbQueueHighWater = 0;
uint32_t usbPacketsSent = 0;
uint32_t packetSequence = 0;
uint32_t lastDiagnosticMs = 0;
uint32_t lastStatusPacketMs = 0;
uint8_t pendingUpdateMask = 0;
uint8_t activeModuleMask = ALL_MODULES_MASK;
uint32_t pendingSinceMs = 0;
uint8_t deltaResyncMask = 0U;
uint8_t spatialResyncMask = 0U;
uint32_t transportEpoch = 0U;
Algorithm selectedAlgorithm = Algorithm::Full;
Algorithm pendingAlgorithm = Algorithm::Full;
bool modeSwitchPending = false;
uint32_t modeSwitchStartedMs = 0;
uint16_t scanHz = DEFAULT_SCAN_HZ;
uint16_t deltaThreshold = 8;
uint16_t spatialThreshold = 128;

void clearPendingTransport();
void beginResync(Algorithm algorithm);

uint32_t moduleOfflineTimeoutMs() {
  if (scanHz == 0U) return MIN_MODULE_OFFLINE_TIMEOUT_MS;
  const uint32_t periodMs =
      (1000UL + (uint32_t)scanHz - 1UL) / (uint32_t)scanHz;
  const uint32_t adaptiveTimeout = periodMs * MODULE_OFFLINE_PERIODS;
  return adaptiveTimeout > MIN_MODULE_OFFLINE_TIMEOUT_MS ?
         adaptiveTimeout : MIN_MODULE_OFFLINE_TIMEOUT_MS;
}

uint16_t readU16LE(const uint8_t *value) {
  return (uint16_t)value[0] | ((uint16_t)value[1] << 8U);
}

uint32_t readU32LE(const uint8_t *value) {
  return (uint32_t)value[0] | ((uint32_t)value[1] << 8U) |
         ((uint32_t)value[2] << 16U) | ((uint32_t)value[3] << 24U);
}

void writeU16LE(uint8_t *target, uint16_t value) {
  target[0] = (uint8_t)value;
  target[1] = (uint8_t)(value >> 8U);
}

void writeU32LE(uint8_t *target, uint32_t value) {
  target[0] = (uint8_t)value;
  target[1] = (uint8_t)(value >> 8U);
  target[2] = (uint8_t)(value >> 16U);
  target[3] = (uint8_t)(value >> 24U);
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

bool markerIs(const uint8_t *value, const uint8_t marker[4]) {
  return memcmp(value, marker, 4U) == 0;
}

const char *algorithmName() {
  switch (selectedAlgorithm) {
    case Algorithm::Delta: return "DELTA";
    case Algorithm::Spatial: return "SPATIAL";
    default: return "FULL";
  }
}

Algorithm algorithmForFrame(const uint8_t *frame) {
  if (markerIs(frame, ESK_FULL)) {
    if ((frame[5] & 0x40U) != 0U) return Algorithm::Spatial;
    if ((frame[5] & 0x20U) != 0U) return Algorithm::Delta;
    return Algorithm::Full;
  }
  if (markerIs(frame, ESK_DELTA)) {
    return Algorithm::Delta;
  }
  if (markerIs(frame, ESP_FULL) || markerIs(frame, ESP_DELTA) ||
      markerIs(frame, ESP_HEARTBEAT)) {
    return Algorithm::Spatial;
  }
  return Algorithm::Full;
}

bool isDeltaSyncFrame(const uint8_t *frame) {
  return markerIs(frame, ESK_FULL) && ((frame[5] & 0x20U) != 0U);
}

bool isSpatialSyncFrame(const uint8_t *frame) {
  return markerIs(frame, ESP_FULL) ||
         (markerIs(frame, ESK_FULL) && ((frame[5] & 0x40U) != 0U));
}

bool waitForLevel(uint8_t pin, uint8_t level, uint32_t timeoutMs) {
  const uint32_t started = millis();
  while (digitalRead(pin) != level) {
    if ((millis() - started) >= timeoutMs) return false;
    yield();
  }
  return true;
}

uint16_t logicalFrameLength(const uint8_t *frame) {
  if (markerIs(frame, ESK_FULL)) {
    if (frame[4] != ESK_PROTOCOL_VERSION ||
        readU16LE(&frame[6]) != HOST_SLOT_BYTES) return 0;
    return HOST_SLOT_BYTES;
  }
  if (markerIs(frame, ESK_DELTA)) {
    if (frame[4] != ESK_PROTOCOL_VERSION) return 0;
    const uint16_t declared = readU16LE(&frame[6]);
    if ((frame[5] & 0x10U) == 0U) return 0;
    uint16_t changed = 0U;
    for (size_t index = 0; index < DELTA_MASK_TOTAL_BYTES; ++index) {
      uint8_t value = frame[16 + index];
      while (value != 0U) {
        changed = (uint16_t)(changed + (value & 1U));
        value = (uint8_t)(value >> 1U);
      }
    }
    const uint16_t expected = (uint16_t)(DELTA_MASK_MIN_FRAME_BYTES +
                                         2U * changed);
    if ((declared != expected) || declared > HOST_SLOT_BYTES ||
        declared < DELTA_MASK_MIN_FRAME_BYTES) return 0;
    return declared;
  }
  if (markerIs(frame, ESP_FULL) || markerIs(frame, ESP_DELTA)) {
    const uint16_t count = readU16LE(&frame[44]);
    const uint16_t declared = (uint16_t)(46U + 4U * count);
    return declared <= HOST_SLOT_BYTES ? declared : 0;
  }
  if (markerIs(frame, ESP_HEARTBEAT)) return 12U;
  return 0;
}

ReadResult readModuleFrame(uint8_t module) {
  ModuleState &state = modules[module];
  uint8_t *frame = moduleFrames[module];
  const uint8_t moduleBit = (uint8_t)(1U << module);
  const bool requestDeltaResync =
      (selectedAlgorithm == Algorithm::Delta) &&
      ((deltaResyncMask & moduleBit) != 0U);
  const bool requestSpatialResync =
      (selectedAlgorithm == Algorithm::Spatial) &&
      ((spatialResyncMask & moduleBit) != 0U);
  uint8_t command[HOST_COMMAND_BYTES];
  fillCommand(command, requestDeltaResync, requestSpatialResync);
  memset(frame, 0, HOST_SLOT_BYTES);
  memcpy(frame, command, HOST_COMMAND_BYTES);
  delayMicroseconds(IRQ_SETTLE_US);
  SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0));
  digitalWrite(CS_PINS[module], LOW);
  delayMicroseconds(CS_SETUP_US);
  SPI.transfer(frame, HOST_SLOT_BYTES);
  delayMicroseconds(CS_HOLD_US);
  digitalWrite(CS_PINS[module], HIGH);
  SPI.endTransaction();

  const uint16_t length = logicalFrameLength(frame);
  if (length == 0U) {
    if (frame[0] == 'E' && frame[1] == 'S' && frame[2] == 'K' &&
        frame[4] != ESK_PROTOCOL_VERSION) {
      return ReadResult::BadVersion;
    }
    return ReadResult::BadFrame;
  }
  if (!markerIs(frame, ESP_FULL) && !markerIs(frame, ESP_DELTA) &&
      !markerIs(frame, ESP_HEARTBEAT)) {
    const uint32_t wire = readU32LE(&frame[length - 4U]);
    if (wire != crc32Ieee(frame, length - 4U)) {
      ++state.crcErrorCount;
      return ReadResult::BadCrc;
    }
  }
  state.frameAlgorithm = algorithmForFrame(frame);
  const uint32_t sequence = readU32LE(&frame[8]);
  const bool sequenceGap =
      state.sequenceSeen && sequence != state.lastSequence + 1U;
  if (sequenceGap) {
    ++state.sequenceGapCount;
  }
  state.lastSequence = sequence;
  state.sequenceSeen = true;

  const bool deltaSync = isDeltaSyncFrame(frame);
  const bool spatialSync = isSpatialSyncFrame(frame);
  if (selectedAlgorithm == Algorithm::Delta &&
      state.frameAlgorithm == Algorithm::Delta && sequenceGap && !deltaSync) {
    /* A Delta base may have been skipped while the USB queue was full. */
    beginResync(Algorithm::Delta);
    return ReadResult::ResyncNeeded;
  }
  if (selectedAlgorithm == Algorithm::Spatial &&
      state.frameAlgorithm == Algorithm::Spatial && sequenceGap &&
      !spatialSync) {
    /* A Spatial delta may have been skipped while the USB queue was full. */
    beginResync(Algorithm::Spatial);
    return ReadResult::ResyncNeeded;
  }
  if (requestDeltaResync) {
    if (!deltaSync) return ReadResult::ResyncNeeded;
    deltaResyncMask &= (uint8_t)~moduleBit;
  }
  if (requestSpatialResync) {
    if (!spatialSync) return ReadResult::ResyncNeeded;
    spatialResyncMask &= (uint8_t)~moduleBit;
  }
  if (state.frameAlgorithm != selectedAlgorithm) {
    return ReadResult::ModeTransition;
  }
  state.logicalLength = length;
  state.haveFrame = true;
  ++state.okCount;
  return ReadResult::Ok;
}

void fillCommand(uint8_t command[HOST_COMMAND_BYTES],
                 bool requestDeltaResync,
                 bool requestSpatialResync) {
  memset(command, 0, HOST_COMMAND_BYTES);
  memcpy(command, COMMAND_MAGIC, 4U);
  command[4] = 2U;
  command[5] = (uint8_t)selectedAlgorithm;
  writeU16LE(&command[6], deltaThreshold);
  writeU16LE(&command[8], spatialThreshold);
  writeU16LE(&command[10], scanHz);
  if (requestDeltaResync) {
    command[12] = COMMAND_FLAG_DELTA_RESYNC;
  }
  if (requestSpatialResync) {
    command[12] |= COMMAND_FLAG_SPATIAL_RESYNC;
  }
}

void clearPendingTransport() {
  ++transportEpoch;
  pendingUpdateMask = 0U;
  pendingSinceMs = 0U;
  if (usbQueueCount > 0U && usbQueueOffset > 0U) {
    /* Bytes from the head packet are already on USB and cannot be recalled.
     * Keep only that packet so its remaining bytes preserve the MUL1 framing;
     * discard every packet that has not started transmission. */
    usbQueueTail = (usbQueueHead + 1U) % USB_QUEUE_DEPTH;
    usbQueueCount = 1U;
  } else {
    usbQueueHead = 0U;
    usbQueueTail = 0U;
    usbQueueCount = 0U;
    usbQueueOffset = 0U;
  }
}

void beginResync(Algorithm algorithm) {
  if (selectedAlgorithm != algorithm) return;
  const uint8_t activeMask = (uint8_t)(activeModuleMask & ALL_MODULES_MASK);
  if (algorithm == Algorithm::Delta) {
    deltaResyncMask = activeMask;
  } else if (algorithm == Algorithm::Spatial) {
    spatialResyncMask = activeMask;
  }
  /* Discard packets that were prepared before the sequence discontinuity.
   * They can contain deltas whose base is no longer available to the PC. */
  clearPendingTransport();
  for (uint8_t module = 0; module < MODULE_COUNT; ++module) {
    modules[module].haveFrame = false;
    modules[module].logicalLength = 0U;
    modules[module].sequenceSeen = false;
    modules[module].lastResult = ReadResult::ResyncNeeded;
  }
}

void requestModeSwitch(Algorithm requestedAlgorithm) {
  pendingAlgorithm = requestedAlgorithm;
  modeSwitchPending = true;
  modeSwitchStartedMs = millis();
  /* Do not let frames from the old mode remain in the USB or round queues
   * while the one-second coordinated switch window is running. */
  clearPendingTransport();
}

void activatePendingModeSwitch() {
  selectedAlgorithm = pendingAlgorithm;
  modeSwitchPending = false;
  modeSwitchStartedMs = 0U;
  clearPendingTransport();
  deltaResyncMask = (selectedAlgorithm == Algorithm::Delta) ?
                    ALL_MODULES_MASK : 0U;
  spatialResyncMask = (selectedAlgorithm == Algorithm::Spatial) ?
                      ALL_MODULES_MASK : 0U;
  for (uint8_t module = 0; module < MODULE_COUNT; ++module) {
    modules[module].haveFrame = false;
    modules[module].logicalLength = 0U;
    modules[module].sequenceSeen = false;
    modules[module].lastResult = ReadResult::ModeTransition;
  }
}

void requestModeResync(Algorithm algorithm) {
  beginResync(algorithm);
}

bool enqueueMultiPacket(uint8_t updatedMask) {
  if (usbQueueCount >= USB_QUEUE_DEPTH) return false;
  uint8_t *packet = usbQueue[usbQueueTail];
  memset(packet, 0, MAX_PACKET_BYTES);
  memcpy(packet, MUL_MAGIC, 4U);
  packet[4] = 2U;
  packet[5] = MODULE_COUNT;
  packet[6] = updatedMask;
  writeU32LE(&packet[12], packetSequence++);
  writeU32LE(&packet[16], millis());

  size_t offset = PACKET_HEADER_BYTES;
  for (uint8_t module = 0; module < MODULE_COUNT; ++module) {
    const bool updated = (updatedMask & (uint8_t)(1U << module)) != 0U;
    packet[offset++] = module;
    if (!updated) {
      /* Do not replay a previous Delta frame. The PC must retain its cache.
       * Keep the last read result in the status byte so a no-data system is
       * diagnosable without mixing text into the binary USB stream. */
      packet[offset++] = (uint8_t)(MODULE_STATUS_NOT_UPDATED |
                                   ((uint8_t)modules[module].lastResult & 0x0FU));
      const bool includeDiagnosticPrefix =
          modules[module].lastResult == ReadResult::BadFrame ||
          modules[module].lastResult == ReadResult::BadCrc ||
          modules[module].lastResult == ReadResult::Timeout ||
          modules[module].lastResult == ReadResult::BadVersion;
      const uint16_t diagnosticLength = includeDiagnosticPrefix ?
          (uint16_t)DIAGNOSTIC_PREFIX_BYTES : 0U;
      writeU16LE(&packet[offset], diagnosticLength);
      offset += 2U;
      if (diagnosticLength != 0U) {
        memcpy(&packet[offset], moduleFrames[module], diagnosticLength);
        offset += diagnosticLength;
      }
      continue;
    }
    packet[offset++] = modules[module].haveFrame ? 0U :
                       (uint8_t)modules[module].lastResult + 1U;
    const uint16_t length = modules[module].haveFrame ?
                            modules[module].logicalLength : 0U;
    writeU16LE(&packet[offset], length);
    offset += 2U;
    if (length != 0U) {
      memcpy(&packet[offset], moduleFrames[module], length);
      offset += length;
    }
  }
  const uint16_t packetLength = (uint16_t)(offset + PACKET_TRAILER_BYTES);
  writeU16LE(&packet[8], packetLength);
  writeU16LE(&packet[10], 0U);
  writeU32LE(&packet[offset], crc32Ieee(packet, offset));
  usbQueueLength[usbQueueTail] = packetLength;
  usbQueueTail = (usbQueueTail + 1U) % USB_QUEUE_DEPTH;
  ++usbQueueCount;
  if (usbQueueCount > usbQueueHighWater) usbQueueHighWater = usbQueueCount;
  return true;
}

void pollModules() {
  if (modeSwitchPending) {
    if ((uint32_t)(millis() - modeSwitchStartedMs) < MODE_SWITCH_DELAY_MS) {
      return;
    }
    activatePendingModeSwitch();
  }

  uint8_t updatedMask = 0U;
  const uint32_t nowMs = millis();
  const uint32_t offlineTimeoutMs = moduleOfflineTimeoutMs();
  const uint32_t pollEpoch = transportEpoch;
  /* The STM32 scan clock is the single rate limiter. Poll IRQ continuously so
   * a ready frame is consumed immediately instead of waiting for another
   * Teensy-side period when the two independent clocks are out of phase. */
  for (uint8_t module = 0; module < MODULE_COUNT; ++module) {
    const uint8_t moduleBit = (uint8_t)(1U << module);
    ModuleState &state = modules[module];
    if ((pendingUpdateMask & moduleBit) != 0U) {
      /* moduleFrames[module] is the immutable snapshot for the pending MUL1
       * round. Reading this module again would overwrite an unsent ESKF/ESKD
       * frame and break the PC's Delta base_sequence chain. This also freezes
       * the first ESKF returned during a coordinated resynchronisation. */
      continue;
    }
    if (digitalRead(IRQ_PINS[module]) != HIGH) {
      if ((activeModuleMask & moduleBit) != 0U &&
          (uint32_t)(nowMs - state.lastIrqMs) >= offlineTimeoutMs) {
        activeModuleMask &= (uint8_t)~moduleBit;
        pendingUpdateMask &= (uint8_t)~moduleBit;
        deltaResyncMask &= (uint8_t)~moduleBit;
        spatialResyncMask &= (uint8_t)~moduleBit;
        state.haveFrame = false;
        state.logicalLength = 0U;
        state.sequenceSeen = false;
        state.lastResult = ReadResult::NoIrq;
      }
      continue;
    }
    state.lastIrqMs = nowMs;
    if ((activeModuleMask & moduleBit) == 0U) {
      /* A reconnected module rejoins immediately. Delta and Spatial need a
       * fresh base before incremental frames can be accepted again. */
      activeModuleMask |= moduleBit;
      state.haveFrame = false;
      state.logicalLength = 0U;
      state.sequenceSeen = false;
      if (selectedAlgorithm == Algorithm::Delta) {
        deltaResyncMask |= moduleBit;
      } else if (selectedAlgorithm == Algorithm::Spatial) {
        spatialResyncMask |= moduleBit;
      }
    }
    ++modules[module].irqCount;
    const ReadResult result = readModuleFrame(module);
    modules[module].lastResult = result;
    if (result == ReadResult::Ok) {
      updatedMask |= moduleBit;
      pendingUpdateMask |= moduleBit;
      if (pendingSinceMs == 0U) pendingSinceMs = millis();
    } else if ((result != ReadResult::ModeTransition) &&
               (result != ReadResult::ResyncNeeded)) {
      ++modules[module].badFrameCount;
    }
    if (!waitForLevel(IRQ_PINS[module], LOW, IRQ_RELEASE_TIMEOUT_MS)) {
      ++modules[module].releaseTimeoutCount;
    }
    if (transportEpoch != pollEpoch) {
      /* A later module in this poll triggered beginResync(). Any frames
       * accepted earlier in the same local round belonged to the old cache
       * generation; clearPendingTransport() has invalidated them. Abort now
       * so a stale local updatedMask cannot reintroduce those frames. */
      return;
    }
  }

  const bool completeRound = activeModuleMask != 0U &&
      (pendingUpdateMask & activeModuleMask) == activeModuleMask;
  const bool timedOut = pendingUpdateMask != 0U &&
                        (millis() - pendingSinceMs) >= MULTI_ROUND_TIMEOUT_MS;
  const bool resyncPending =
      (selectedAlgorithm == Algorithm::Delta) ?
          ((deltaResyncMask & activeModuleMask) != 0U) :
      (selectedAlgorithm == Algorithm::Spatial) ?
          ((spatialResyncMask & activeModuleMask) != 0U) : false;
  if ((completeRound || timedOut) && !resyncPending) {
    if (enqueueMultiPacket(pendingUpdateMask)) {
      lastStatusPacketMs = millis();
      pendingUpdateMask = 0U;
      pendingSinceMs = 0U;
    } else if (selectedAlgorithm == Algorithm::Delta) {
      /* The packet was not queued. A later Delta frame may reference a
       * sequence that the PC never received, so force a full Delta sync. */
      beginResync(Algorithm::Delta);
    } else if (selectedAlgorithm == Algorithm::Spatial) {
      /* The packet was not queued. A later Spatial delta may reference a
       * state that the PC never received, so force a Spatial base frame. */
      beginResync(Algorithm::Spatial);
    }
  }

  /* Always provide a low-rate diagnostic MUL1 packet when no module has
   * produced a valid frame. This keeps the USB/parser path observable and
   * reports whether each module has no IRQ, a bad frame, a CRC error, or a
   * timeout. It is intentionally rate-limited so it cannot affect scanning. */
  if ((updatedMask == 0U) &&
      ((millis() - lastStatusPacketMs) >= STATUS_PACKET_INTERVAL_MS)) {
    if (enqueueMultiPacket(0U)) {
      lastStatusPacketMs = millis();
    }
  }
}

void drainUsbQueue() {
  while (usbQueueCount > 0U) {
    const int available = Serial.availableForWrite();
    if (available <= 0) return;
    const size_t packetLength = usbQueueLength[usbQueueHead];
    const size_t remaining = packetLength - usbQueueOffset;
    const size_t chunk = remaining < (size_t)available ? remaining :
                         (size_t)available;
    const size_t written = Serial.write(usbQueue[usbQueueHead] +
                                        usbQueueOffset, chunk);
    if (written == 0U) return;
    usbQueueOffset += written;
    if (usbQueueOffset == packetLength) {
      usbQueueOffset = 0U;
      usbQueueHead = (usbQueueHead + 1U) % USB_QUEUE_DEPTH;
      --usbQueueCount;
      ++usbPacketsSent;
    }
  }
}

void handleUsbCommands() {
  static char line[48];
  static size_t used = 0U;
  while (Serial.available() > 0) {
    const char value = (char)Serial.read();
    if (value == '\n' || value == '\r') {
      if (used == 0U) continue;
      line[used] = '\0';
      Algorithm requestedAlgorithm = selectedAlgorithm;
      bool modeCommand = false;
      if (strncmp(line, "MODE FULL", 9U) == 0) {
        requestedAlgorithm = Algorithm::Full;
        modeCommand = true;
      } else if (strncmp(line, "MODE DELTA", 10U) == 0) {
        requestedAlgorithm = Algorithm::Delta;
        modeCommand = true;
      } else if (strncmp(line, "MODE SPATIAL", 12U) == 0) {
        requestedAlgorithm = Algorithm::Spatial;
        modeCommand = true;
      }
      if (modeCommand) {
        if (modeSwitchPending && requestedAlgorithm == selectedAlgorithm) {
          /* A command back to the active mode cancels a pending switch. */
          modeSwitchPending = false;
          modeSwitchStartedMs = 0U;
        } else if (requestedAlgorithm != selectedAlgorithm) {
          requestModeSwitch(requestedAlgorithm);
        }
      } else if (strncmp(line, "RESYNC DELTA", 12U) == 0) {
        requestModeResync(Algorithm::Delta);
      } else if (strncmp(line, "RESYNC SPATIAL", 14U) == 0) {
        requestModeResync(Algorithm::Spatial);
      } else if (strncmp(line, "SCAN_HZ ", 9U) == 0) {
        long valueHz = atol(line + 9);
        if (valueHz < 0) valueHz = 0;
      if (valueHz > 1000) valueHz = 1000;
      scanHz = (uint16_t)valueHz;
      }
      used = 0U;
    } else if (used + 1U < sizeof(line)) {
      line[used++] = value;
    } else {
      used = 0U;
    }
  }
}

void setup() {
  const uint32_t startedMs = millis();
  for (uint8_t module = 0; module < MODULE_COUNT; ++module) {
    pinMode(CS_PINS[module], OUTPUT);
    digitalWrite(CS_PINS[module], HIGH);
    pinMode(IRQ_PINS[module], INPUT_PULLDOWN);
    modules[module].lastIrqMs = startedMs;
  }
  SPI.begin();
  Serial.begin(USB_BAUD);
}

void loop() {
  handleUsbCommands();
  /* Module acquisition must not depend on the USB CDC ready flag. Some host
   * drivers expose the port before Teensy::Serial evaluates as connected. */
  pollModules();
  drainUsbQueue();
}
