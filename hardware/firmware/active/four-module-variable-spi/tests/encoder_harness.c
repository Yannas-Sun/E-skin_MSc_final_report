/* Compiled after the real protocol .c, independently for baseline and candidate. */
#include <assert.h>
#include <stdio.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
static uint16_t samples_a[256], samples_b[256];
static unsigned frames_written;
static void emit_frame(uint32_t now, uint16_t expected_length)
{
  struct { uint8_t before[16], frame[1044], after[16]; } guarded;
  memset(&guarded, 0xA5, sizeof(guarded));
  uint16_t length = DataScalability_Encode(guarded.frame, samples_a, samples_b, now, 3);
  assert(length >= 84 && length <= 1044);
  if (expected_length) assert(length == expected_length);
  for (unsigned i = 0; i < 16; ++i) assert(guarded.before[i] == 0xA5 && guarded.after[i] == 0xA5);
  for (unsigned i = length; i < 1044; ++i) assert(guarded.frame[i] == 0);
  assert(fwrite(&length, 2, 1, stdout) == 1);
  assert(fwrite(guarded.frame, 1044, 1, stdout) == 1);
  ++frames_written;
}
static void command(uint8_t mode_value, uint16_t threshold, uint8_t flags)
{
  uint8_t bytes[16] = {'D','S','C','M',2,0};
  bytes[5] = mode_value;
  bytes[6] = (uint8_t)threshold; bytes[7] = (uint8_t)(threshold >> 8);
  bytes[8] = 0xAA; bytes[9] = 0x55;
  bytes[10] = 200; bytes[12] = flags;
  DataScalability_ApplyCommand(bytes, sizeof(bytes));
  assert(DataScalability_GetScanRateHz() == 200);
}
int main(void)
{
#ifdef _WIN32
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  DataScalability_Init();
  assert(DataScalability_Encode(NULL, samples_a, samples_b, 0, 3) == 0);
  emit_frame(0, 1044);
  for (unsigned i = 0; i < 256; ++i) { samples_a[i] = i * 7; samples_b[i] = 4095 - i * 9; }
  emit_frame(1, 1044);
  command(1, 8, 0);
  emit_frame(2, 1044);
  emit_frame(3, 84);
  samples_a[0] += 8; samples_b[255] -= 8;
  emit_frame(4, 84);
  samples_a[0] += 9; samples_b[255] -= 9;
  emit_frame(5, 88);
  emit_frame(1002, 1044);
  command(1, 8, 1);
  emit_frame(1003, 1044);
  for (unsigned i = 0; i < 256; ++i) { samples_a[i] += 100; if (i < 224) samples_b[i] += 100; }
  emit_frame(1004, 1044);
  for (unsigned i = 0; i < 256; ++i) { samples_a[i] += 100; if (i < 225) samples_b[i] += 100; }
  emit_frame(1005, 1044);
  uint32_t random = 0x91ABCDEF;
  for (unsigned step = 0; step < 200; ++step) {
    if (step % 31 == 0) command((uint8_t)((step / 31) & 1), 8, 0);
    for (unsigned j = 0; j < step % 73; ++j) {
      random = random * 1664525U + 1013904223U;
      unsigned i = (random >> 8) & 255;
      if (random & 1) samples_a[i] = (uint16_t)(random >> 16);
      else samples_b[i] = (uint16_t)(random >> 16);
    }
    emit_frame(1010 + step * 5, 0);
  }
  command(1, 8, 0);
  emit_frame(0xFFFFFFF0U, 1044);
  emit_frame(5, 84);
#ifndef BASELINE
  DataScalability_SetMode(2);
  assert(DataScalability_GetMode() == 1);
#endif
  fprintf(stderr, "encoder: %u frames; threshold/fallback/resync/wrap/canary passed\n", frames_written);
  return 0;
}
