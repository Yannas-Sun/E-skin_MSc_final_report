/* Included after the actual .ino; mock the pins and peripheral, not the parser. */
#include <stdio.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
uint32_t mock_ms = 1234;
int mock_cs = -1, mock_cs_lows = 0, mock_cs_highs = 0;
uint8_t mock_pin_levels[256] = {};
MockSerial Serial;
MockSPI SPI;
static unsigned checks;

static std::vector<uint8_t> make_frame(bool delta, unsigned changes = 0, uint32_t sequence = 0)
{
  size_t length = delta ? 84 + 2 * changes : 1044;
  std::vector<uint8_t> bytes(length, 0);
  memcpy(bytes.data(), delta ? "ESKD" : "ESKF", 4);
  bytes[4] = 4; bytes[5] = delta ? 0x33 : 0x13;
  writeU16LE(&bytes[6], (uint16_t)length);
  writeU32LE(&bytes[8], sequence);
  writeU32LE(&bytes[12], delta ? sequence - 1 : 0xFFFFFFFFU);
  if (delta) {
    for (unsigned i = 0; i < changes; ++i) {
      bytes[16 + i / 8] |= (uint8_t)(1U << (i % 8));
      writeU16LE(&bytes[80 + 2 * i], (uint16_t)(123 + i));
    }
  } else {
    for (unsigned i = 16; i < 1040; ++i) bytes[i] = (uint8_t)(i * 7);
  }
  writeU32LE(&bytes[length - 4], crc32Ieee(bytes.data(), length - 4));
  return bytes;
}
static void reset_state()
{
  for (unsigned i = 0; i < 4; ++i) modules[i] = ModuleState{};
  memset(moduleFrames, 0, sizeof(moduleFrames));
  selectedAlgorithm = Algorithm::Full;
  deltaResyncMask = 0; activeModuleMask = 15;
  pendingUpdateMask = 0; pendingSinceMs = 0; transportEpoch = 0;
  usbQueueHead = usbQueueTail = usbQueueCount = usbQueueOffset = 0;
  packetSequence = 0; mock_ms = 1234;
  modeSwitchPending = false;
  Serial.input.clear(); Serial.position = 0; Serial.written.clear();
}
static void check_read(std::vector<uint8_t> bytes, ReadResult expected, bool header_valid = true, unsigned module = 0)
{
  SPI.reset(bytes);
  ReadResult result = readModuleFrame((uint8_t)module);
  assert(result == expected);
  assert(mock_cs_lows == 1 && mock_cs_highs == 1 && mock_cs == -1);
  assert(!SPI.transaction);
#ifdef BASELINE
  assert(SPI.chunks.size() == 1 && SPI.chunks[0] == 1044);
#else
  assert(SPI.chunks[0] == 16);
  if (header_valid) {
    assert(SPI.chunks.size() == 2);
    assert(SPI.chunks[1] == bytes.size() - 16);
    assert(SPI.offset == bytes.size());
  } else { assert(SPI.chunks.size() == 1 && SPI.offset == 16); }
#endif
  assert(memcmp(SPI.sent.data(), "DSCM", 4) == 0);
  assert(SPI.sent[4] == 2 && SPI.sent[5] == (uint8_t)selectedAlgorithm);
  assert(readU16LE(&SPI.sent[10]) == 200);
  for (size_t i = 16; i < SPI.sent.size(); ++i) assert(SPI.sent[i] == 0);
  ++checks;
}
static void emit_packet(uint8_t updated)
{
  assert(enqueueMultiPacket(updated));
  uint16_t length = usbQueueLength[usbQueueHead];
  assert(fwrite(&length, 2, 1, stdout) == 1);
  assert(fwrite(usbQueue[usbQueueHead], length, 1, stdout) == 1);
  drainUsbQueue();
  assert(Serial.written.size() == length);
  assert(usbQueueCount == 0);
  Serial.written.clear();
}
int main()
{
#ifdef _WIN32
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  reset_state();
  check_read(make_frame(false), ReadResult::Ok);
  reset_state(); selectedAlgorithm = Algorithm::Delta;
  check_read(make_frame(true), ReadResult::Ok);
  reset_state(); selectedAlgorithm = Algorithm::Delta;
  check_read(make_frame(true, 2), ReadResult::Ok);
  reset_state(); selectedAlgorithm = Algorithm::Delta;
  check_read(make_frame(true, 480), ReadResult::Ok);
  reset_state();
  auto bad = make_frame(false); bad.back() ^= 1;
  check_read(bad, ReadResult::BadCrc);
  reset_state();
  bad = make_frame(false); bad[0] = 'X';
  check_read(bad, ReadResult::BadFrame, false);
  reset_state();
  bad = make_frame(false); bad[4] = 3;
  check_read(bad, ReadResult::BadVersion, false);
  reset_state();
  bad = make_frame(false); writeU16LE(&bad[6], 1042);
  check_read(bad, ReadResult::BadFrame, false);
  reset_state(); selectedAlgorithm = Algorithm::Delta;
  bad = make_frame(true, 1); bad[16] = 0; /* payload-mask mismatch */
  check_read(bad, ReadResult::BadFrame);
#ifndef BASELINE
  for (uint16_t length : {0, 15, 20, 83, 85, 1046, 65535}) {
    reset_state(); selectedAlgorithm = Algorithm::Delta;
    bad = make_frame(true); writeU16LE(&bad[6], length);
    check_read(bad, ReadResult::BadFrame, false);
  }
  for (uint8_t flags : {0x03, 0x13, 0x73, 0xB3}) {
    reset_state(); selectedAlgorithm = Algorithm::Delta;
    bad = make_frame(true); bad[5] = flags;
    check_read(bad, ReadResult::BadFrame, false);
  }
  reset_state(); bad = make_frame(false); memcpy(bad.data(), "XXXX", 4);
  check_read(bad, ReadResult::BadFrame, false);
  reset_state(); Serial.input = "MODE UNKNOWN\nRESYNC UNKNOWN\n";
  handleUsbCommands(); assert(!modeSwitchPending && selectedAlgorithm == Algorithm::Full);
  reset_state(); selectedAlgorithm = Algorithm::Delta;
  modules[0].sequenceSeen = true; modules[0].lastSequence = 3;
  modules[0].frameAlgorithm = Algorithm::Delta;
  check_read(make_frame(true, 0, 5), ReadResult::ResyncNeeded);
  assert(deltaResyncMask == 15 && pendingUpdateMask == 0);
#endif
  /* Exact byte comparison against the old bridge: all four slot positions. */
  reset_state();
  for (unsigned module = 0; module < 4; ++module) check_read(make_frame(false, 0, module), ReadResult::Ok, true, module);
  emit_packet(15);
  reset_state(); selectedAlgorithm = Algorithm::Delta;
  for (unsigned module = 0; module < 4; ++module) check_read(make_frame(true, module, module), ReadResult::Ok, true, module);
  modules[1].lastResult = ReadResult::BadCrc;
  modules[3].lastResult = ReadResult::NoIrq;
  emit_packet(5); /* slots 1 and 3 stay present with NOT_UPDATED status */
  fprintf(stderr, "Teensy: %u real readModuleFrame calls; CS/length/error/USB checks passed\n", checks);
  return 0;
}
