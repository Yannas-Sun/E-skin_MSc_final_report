#include "data_scalability_protocol.h"

#include <stddef.h>
#include <string.h>

#define FSR_CELLS 256U
#define FSR_BYTES 512U
#define ESK_HEADER_BYTES 16U
#define ESK_TRAILER_BYTES 4U
#define DELTA_MASK_BYTES 32U
#define DELTA_MASK_TOTAL_BYTES (2U * DELTA_MASK_BYTES)
#define DELTA_MASK_PREFIX_BYTES (ESK_HEADER_BYTES + DELTA_MASK_TOTAL_BYTES)
#define DELTA_MAX_VALUES ((DATA_SCALABILITY_FRAME_BYTES - DELTA_MASK_PREFIX_BYTES - ESK_TRAILER_BYTES) / 2U)

#define PROTOCOL_VERSION 4U
#define FLAG_CRC_PRESENT 0x10U
#define FLAG_DELTA_FRAME 0x20U

#define DELTA_DEFAULT_THRESHOLD 8U
#define DELTA_RESYNC_INTERVAL_MS 1000U

#ifndef DATA_SCALABILITY_DEFAULT_MODE
#define DATA_SCALABILITY_DEFAULT_MODE DATA_SCALABILITY_MODE_FULL
#endif

#if (DATA_SCALABILITY_DEFAULT_MODE < DATA_SCALABILITY_MODE_FULL) || \
    (DATA_SCALABILITY_DEFAULT_MODE > DATA_SCALABILITY_MODE_DELTA)
#error "DATA_SCALABILITY_DEFAULT_MODE must be 0 or 1"
#endif

static const uint8_t MAGIC_ESKF[4] = {'E', 'S', 'K', 'F'};
static const uint8_t MAGIC_ESKD[4] = {'E', 'S', 'K', 'D'};
static const uint8_t COMMAND_MAGIC[4] = {'D', 'S', 'C', 'M'};

static uint16_t previous_fsr1[FSR_CELLS];
static uint16_t previous_fsr2[FSR_CELLS];
static uint8_t mode;
static uint8_t delta_cache_valid;
static uint16_t delta_threshold;
static uint16_t scan_rate_hz;
static uint32_t next_sequence;
static uint32_t cache_sequence;
static uint32_t last_delta_full_sync_ms;

static void mask_clear(uint8_t mask[DELTA_MASK_BYTES]);
static void mask_set(uint8_t mask[DELTA_MASK_BYTES], uint8_t row,
                     uint8_t column);
static uint8_t mask_get(const uint8_t mask[DELTA_MASK_BYTES],
                        uint16_t position);

static uint16_t read_u16(const uint8_t *data)
{
  return (uint16_t)data[0] | ((uint16_t)data[1] << 8U);
}

static void put_u16(uint8_t *data, uint32_t *offset, uint16_t value)
{
  data[(*offset)++] = (uint8_t)value;
  data[(*offset)++] = (uint8_t)(value >> 8U);
}

static void put_u32(uint8_t *data, uint32_t *offset, uint32_t value)
{
  put_u16(data, offset, (uint16_t)value);
  put_u16(data, offset, (uint16_t)(value >> 16U));
}

static uint16_t absolute_difference(uint16_t left, uint16_t right)
{
  return (left >= right) ? (uint16_t)(left - right)
                         : (uint16_t)(right - left);
}

static uint32_t crc32_ieee(const uint8_t *data, uint32_t length)
{
  uint32_t crc = 0xFFFFFFFFU;
  for (uint32_t i = 0U; i < length; ++i)
  {
    crc ^= data[i];
    for (uint8_t bit = 0U; bit < 8U; ++bit)
    {
      const uint32_t mask = (uint32_t)-(int32_t)(crc & 1U);
      crc = (crc >> 1U) ^ (0xEDB88320U & mask);
    }
  }
  return ~crc;
}

static void copy_current(const uint16_t *fsr1, const uint16_t *fsr2)
{
  memcpy(previous_fsr1, fsr1, FSR_BYTES);
  memcpy(previous_fsr2, fsr2, FSR_BYTES);
}

static void write_esk_header(uint8_t *target,
                             const uint8_t marker[4],
                             uint8_t flags,
                             uint16_t length,
                             uint32_t sequence,
                             uint32_t base_sequence)
{
  uint32_t offset = 0U;
  memcpy(target, marker, 4U);
  offset = 4U;
  target[offset++] = PROTOCOL_VERSION;
  target[offset++] = flags;
  put_u16(target, &offset, length);
  put_u32(target, &offset, sequence);
  put_u32(target, &offset, base_sequence);
}

static void write_esk_trailer(uint8_t *target, uint16_t length)
{
  uint32_t offset = (uint32_t)length - ESK_TRAILER_BYTES;
  put_u32(target, &offset, crc32_ieee(target, offset));
}

static uint16_t pack_esk_full(uint8_t *target,
                              const uint16_t *fsr1,
                              const uint16_t *fsr2,
                              uint8_t base_flags,
                              uint32_t now_ms)
{
  const uint32_t sequence = next_sequence++;
  const uint16_t length = DATA_SCALABILITY_FRAME_BYTES;
  write_esk_header(target, MAGIC_ESKF,
                   (uint8_t)(base_flags | FLAG_CRC_PRESENT),
                   length, sequence, 0xFFFFFFFFU);
  memcpy(&target[16U], fsr1, FSR_BYTES);
  memcpy(&target[16U + FSR_BYTES], fsr2, FSR_BYTES);
  write_esk_trailer(target, length);
  copy_current(fsr1, fsr2);
  delta_cache_valid = 1U;
  cache_sequence = sequence;
  last_delta_full_sync_ms = now_ms;
  return length;
}

static uint16_t pack_esk_delta(uint8_t *target,
                               const uint16_t *fsr1,
                               const uint16_t *fsr2,
                               uint8_t base_flags,
                               uint32_t now_ms)
{
  if ((delta_cache_valid == 0U) ||
      ((now_ms - last_delta_full_sync_ms) >= DELTA_RESYNC_INTERVAL_MS))
  {
    return pack_esk_full(target, fsr1, fsr2,
                         (uint8_t)(base_flags | FLAG_DELTA_FRAME), now_ms);
  }

  uint8_t changed_mask[2][DELTA_MASK_BYTES];
  mask_clear(changed_mask[0]);
  mask_clear(changed_mask[1]);
  uint16_t changed = 0U;
  for (uint8_t layer = 0U; layer < 2U; ++layer)
  {
    const uint16_t *current = (layer == 0U) ? fsr1 : fsr2;
    const uint16_t *previous = (layer == 0U) ? previous_fsr1 : previous_fsr2;
    for (uint8_t row = 0U; row < 16U; ++row)
    {
      for (uint8_t column = 0U; column < 16U; ++column)
      {
        const uint16_t index = (uint16_t)row * 16U + column;
        if (absolute_difference(current[index], previous[index]) <=
            delta_threshold)
        {
          continue;
        }
        mask_set(changed_mask[layer], row, column);
        ++changed;
      }
    }
  }

  /* A mask Delta frame must fit the Host SPI buffer. If all or nearly all
   * cells change, send a complete frame instead of truncating the values. */
  if (changed > DELTA_MAX_VALUES)
  {
    return pack_esk_full(target, fsr1, fsr2,
                         (uint8_t)(base_flags | FLAG_DELTA_FRAME), now_ms);
  }

  const uint32_t sequence = next_sequence++;
  const uint32_t base_sequence = cache_sequence;
  const uint16_t length = (uint16_t)(DELTA_MASK_PREFIX_BYTES +
                                     2U * changed + ESK_TRAILER_BYTES);
  write_esk_header(target, MAGIC_ESKD,
                   (uint8_t)(base_flags | FLAG_CRC_PRESENT | FLAG_DELTA_FRAME),
                   length, sequence, base_sequence);
  uint32_t offset = ESK_HEADER_BYTES;
  memcpy(&target[offset], changed_mask[0], DELTA_MASK_BYTES);
  offset += DELTA_MASK_BYTES;
  memcpy(&target[offset], changed_mask[1], DELTA_MASK_BYTES);
  offset += DELTA_MASK_BYTES;
  for (uint8_t layer = 0U; layer < 2U; ++layer)
  {
    const uint16_t *current = (layer == 0U) ? fsr1 : fsr2;
    for (uint16_t position = 0U; position < FSR_CELLS; ++position)
    {
      if (mask_get(changed_mask[layer], position) == 0U)
      {
        continue;
      }
      put_u16(target, &offset, current[position]);
    }
  }
  write_esk_trailer(target, length);
  copy_current(fsr1, fsr2);
  cache_sequence = sequence;
  return length;
}

static void mask_clear(uint8_t mask[DELTA_MASK_BYTES])
{
  memset(mask, 0, DELTA_MASK_BYTES);
}

static void mask_set(uint8_t mask[DELTA_MASK_BYTES], uint8_t row, uint8_t column)
{
  if ((row < 16U) && (column < 16U))
  {
    const uint16_t position = (uint16_t)row * 16U + column;
    mask[position >> 3U] |= (uint8_t)(1U << (position & 7U));
  }
}

static uint8_t mask_get(const uint8_t mask[DELTA_MASK_BYTES], uint16_t position)
{
  return (uint8_t)((mask[position >> 3U] >> (position & 7U)) & 1U);
}

void DataScalability_Init(void)
{
  memset(previous_fsr1, 0, sizeof(previous_fsr1));
  memset(previous_fsr2, 0, sizeof(previous_fsr2));
  mode = DATA_SCALABILITY_DEFAULT_MODE;
  delta_cache_valid = 0U;
  delta_threshold = DELTA_DEFAULT_THRESHOLD;
  scan_rate_hz = 0U;
  next_sequence = 0U;
  cache_sequence = 0xFFFFFFFFU;
  last_delta_full_sync_ms = 0U;
}

void DataScalability_SetMode(uint8_t requested_mode)
{
  if (requested_mode > DATA_SCALABILITY_MODE_DELTA) { return; }
  if (mode == requested_mode) { return; }
  mode = requested_mode;
  delta_cache_valid = 0U;
  last_delta_full_sync_ms = 0U;
}

uint8_t DataScalability_GetMode(void)
{
  return mode;
}

void DataScalability_ApplyCommand(const uint8_t *command, uint16_t length)
{
  if ((command == NULL) || (length < DATA_SCALABILITY_COMMAND_BYTES) ||
      (memcmp(command, COMMAND_MAGIC, 4U) != 0) || (command[4] != 2U))
  {
    return;
  }
  DataScalability_SetMode(command[5]);
  if ((command[12] & DATA_SCALABILITY_COMMAND_FLAG_DELTA_RESYNC) != 0U &&
      mode == DATA_SCALABILITY_MODE_DELTA)
  {
    /* The host may have missed one or more Delta frames. Force the next
     * encoded frame to be a complete Delta base for PC-side recovery. */
    delta_cache_valid = 0U;
    cache_sequence = 0xFFFFFFFFU;
    last_delta_full_sync_ms = 0U;
  }
  const uint16_t requested_delta = read_u16(&command[6]);
  /* DSCM v2 bytes 8..9 remain reserved; do not shift the scan-rate field. */
  const uint16_t requested_rate = read_u16(&command[10]);
  if (requested_delta != 0U) { delta_threshold = requested_delta; }
  scan_rate_hz = requested_rate;
}

uint16_t DataScalability_GetScanRateHz(void)
{
  return scan_rate_hz;
}

uint16_t DataScalability_Encode(uint8_t *target,
                                const uint16_t *fsr1,
                                const uint16_t *fsr2,
                                uint32_t now_ms,
                                uint8_t base_flags)
{
  if ((target == NULL) || (fsr1 == NULL) || (fsr2 == NULL))
  {
    return 0U;
  }
  memset(target, 0, DATA_SCALABILITY_FRAME_BYTES);
  if (mode == DATA_SCALABILITY_MODE_DELTA)
  {
    return pack_esk_delta(target, fsr1, fsr2, base_flags, now_ms);
  }
  return pack_esk_full(target, fsr1, fsr2, base_flags, now_ms);
}
