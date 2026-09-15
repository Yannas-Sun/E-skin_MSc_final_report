#include "data_scalability_protocol.h"

#include <stddef.h>
#include <string.h>

#define FSR_CELLS 256U
#define FSR_BYTES 512U
#define ACC_BYTES 144U
#define ESK_HEADER_BYTES 16U
#define ESK_TRAILER_BYTES 4U
#define SPATIAL_MASK_BYTES 32U
#define SPATIAL_PREFIX_BYTES 142U
#define SPATIAL_HEARTBEAT_BYTES 12U

#define PROTOCOL_VERSION 2U
#define FLAG_ACC_PRESENT 0x04U
#define FLAG_CRC_PRESENT 0x10U
#define FLAG_DELTA_FRAME 0x20U
#define FLAG_SPATIAL_FRAME 0x40U

#define DELTA_DEFAULT_THRESHOLD 8U
#define DELTA_RESYNC_INTERVAL_MS 1000U
#define SPATIAL_DEFAULT_TRIGGER 128U
#define SPATIAL_ACTIVE_HOLD_MS 1000U
#define SPATIAL_MAX_CHANGED_RECORDS 255U

#ifndef DATA_SCALABILITY_DEFAULT_MODE
#define DATA_SCALABILITY_DEFAULT_MODE DATA_SCALABILITY_MODE_FULL
#endif

#if (DATA_SCALABILITY_DEFAULT_MODE < DATA_SCALABILITY_MODE_FULL) || \
    (DATA_SCALABILITY_DEFAULT_MODE > DATA_SCALABILITY_MODE_SPATIAL)
#error "DATA_SCALABILITY_DEFAULT_MODE must be 0, 1 or 2"
#endif

static const uint8_t MAGIC_ESKF[4] = {'E', 'S', 'K', 'F'};
static const uint8_t MAGIC_ESKD[4] = {'E', 'S', 'K', 'D'};
static const uint8_t MAGIC_ESK0[4] = {'E', 'S', 'K', '0'};
static const uint8_t MAGIC_ESPF[4] = {'E', 'S', 'P', 'F'};
static const uint8_t MAGIC_ESPD[4] = {'E', 'S', 'P', 'D'};
static const uint8_t MAGIC_ESP0[4] = {'E', 'S', 'P', '0'};
static const uint8_t COMMAND_MAGIC[4] = {'D', 'S', 'C', 'M'};

static uint16_t previous_fsr1[FSR_CELLS];
static uint16_t previous_fsr2[FSR_CELLS];
static uint16_t spatial_baseline1[FSR_CELLS];
static uint16_t spatial_baseline2[FSR_CELLS];
static uint8_t active_mask[SPATIAL_MASK_BYTES];
static uint8_t previous_mask[SPATIAL_MASK_BYTES];
static uint8_t mode;
static uint8_t delta_cache_valid;
static uint8_t spatial_baseline_valid;
static uint8_t spatial_cache_valid;
static uint16_t delta_threshold;
static uint16_t spatial_trigger_threshold;
static uint32_t next_sequence;
static uint32_t cache_sequence;
static uint32_t last_delta_full_sync_ms;
static uint32_t last_spatial_trigger_ms;

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
                              const uint8_t *acc_wire_144,
                              uint8_t base_flags,
                              uint32_t now_ms)
{
  const uint32_t sequence = next_sequence++;
  const uint16_t length = 1188U;
  write_esk_header(target, MAGIC_ESKF,
                   (uint8_t)(base_flags | FLAG_ACC_PRESENT | FLAG_CRC_PRESENT),
                   length, sequence, 0xFFFFFFFFU);
  memcpy(&target[16U], fsr1, FSR_BYTES);
  memcpy(&target[16U + FSR_BYTES], fsr2, FSR_BYTES);
  memcpy(&target[16U + 2U * FSR_BYTES], acc_wire_144, ACC_BYTES);
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
                               const uint8_t *acc_wire_144,
                               uint8_t base_flags,
                               uint32_t now_ms)
{
  if ((delta_cache_valid == 0U) ||
      ((now_ms - last_delta_full_sync_ms) >= DELTA_RESYNC_INTERVAL_MS))
  {
    return pack_esk_full(target, fsr1, fsr2, acc_wire_144, base_flags, now_ms);
  }

  uint16_t changed = 0U;
  for (uint16_t index = 0U; index < FSR_CELLS; ++index)
  {
    if (absolute_difference(fsr1[index], previous_fsr1[index]) > delta_threshold)
    {
      ++changed;
    }
    if (absolute_difference(fsr2[index], previous_fsr2[index]) > delta_threshold)
    {
      ++changed;
    }
  }

  /* A variable Delta frame must never exceed the fixed 1188-byte SPI slot. */
  if (changed > SPATIAL_MAX_CHANGED_RECORDS)
  {
    return pack_esk_full(target, fsr1, fsr2, acc_wire_144, base_flags, now_ms);
  }

  const uint32_t sequence = next_sequence++;
  const uint32_t base_sequence = cache_sequence;
  const uint16_t length = (changed == 0U)
                              ? 164U
                              : (uint16_t)(166U + 4U * changed);
  const uint8_t *marker = (changed == 0U) ? MAGIC_ESK0 : MAGIC_ESKD;
  write_esk_header(target, marker,
                   (uint8_t)(base_flags | FLAG_ACC_PRESENT |
                             FLAG_CRC_PRESENT | FLAG_DELTA_FRAME),
                   length, sequence, base_sequence);
  memcpy(&target[16U], acc_wire_144, ACC_BYTES);

  uint32_t offset = 160U;
  if (changed != 0U)
  {
    put_u16(target, &offset, changed);
    for (uint8_t layer = 0U; layer < 2U; ++layer)
    {
      const uint16_t *current = (layer == 0U) ? fsr1 : fsr2;
      const uint16_t *previous = (layer == 0U) ? previous_fsr1 : previous_fsr2;
      for (uint8_t row = 0U; row < 16U; ++row)
      {
        for (uint8_t column = 0U; column < 16U; ++column)
        {
          const uint16_t index = (uint16_t)row * 16U + column;
          if (absolute_difference(current[index], previous[index]) <= delta_threshold)
          {
            continue;
          }
          target[offset++] = (uint8_t)(((uint8_t)layer << 7U) | row);
          target[offset++] = column;
          put_u16(target, &offset, current[index]);
        }
      }
    }
  }
  write_esk_trailer(target, length);
  copy_current(fsr1, fsr2);
  cache_sequence = sequence;
  return length;
}

static void mask_clear(uint8_t mask[SPATIAL_MASK_BYTES])
{
  memset(mask, 0, SPATIAL_MASK_BYTES);
}

static void mask_set(uint8_t mask[SPATIAL_MASK_BYTES], uint8_t row, uint8_t column)
{
  if ((row < 16U) && (column < 16U))
  {
    const uint16_t position = (uint16_t)row * 16U + column;
    mask[position >> 3U] |= (uint8_t)(1U << (position & 7U));
  }
}

static uint8_t mask_get(const uint8_t mask[SPATIAL_MASK_BYTES], uint16_t position)
{
  return (uint8_t)((mask[position >> 3U] >> (position & 7U)) & 1U);
}

static uint16_t mask_count(const uint8_t mask[SPATIAL_MASK_BYTES])
{
  uint16_t count = 0U;
  for (uint16_t position = 0U; position < FSR_CELLS; ++position)
  {
    count = (uint16_t)(count + mask_get(mask, position));
  }
  return count;
}

static void build_sentinel_mask(uint8_t mask[SPATIAL_MASK_BYTES])
{
  static const uint8_t sentinel[6] = {1U, 4U, 6U, 9U, 11U, 14U};
  mask_clear(mask);
  for (uint8_t row = 0U; row < 16U; ++row)
  {
    for (uint8_t index = 0U; index < 6U; ++index)
    {
      mask_set(mask, row, sentinel[index]);
      mask_set(mask, sentinel[index], row);
    }
  }
}

static void build_spatial_mask(uint8_t next_mask[SPATIAL_MASK_BYTES],
                               const uint16_t *fsr1,
                               const uint16_t *fsr2,
                               uint32_t now_ms)
{
  if (spatial_baseline_valid == 0U)
  {
    memcpy(spatial_baseline1, fsr1, FSR_BYTES);
    memcpy(spatial_baseline2, fsr2, FSR_BYTES);
    spatial_baseline_valid = 1U;
    build_sentinel_mask(next_mask);
    return;
  }

  uint8_t trigger[FSR_CELLS] = {0U};
  uint8_t any_trigger = 0U;
  for (uint16_t position = 0U; position < FSR_CELLS; ++position)
  {
    if ((absolute_difference(fsr1[position], spatial_baseline1[position]) >
         spatial_trigger_threshold) ||
        (absolute_difference(fsr2[position], spatial_baseline2[position]) >
         spatial_trigger_threshold))
    {
      trigger[position] = 1U;
      any_trigger = 1U;
    }
  }

  if (any_trigger != 0U)
  {
    last_spatial_trigger_ms = now_ms;
    mask_clear(next_mask);
    for (uint8_t row = 0U; row < 16U; ++row)
    {
      for (uint8_t column = 0U; column < 16U; ++column)
      {
        const uint16_t position = (uint16_t)row * 16U + column;
        if (trigger[position] == 0U) { continue; }
        for (int8_t dr = -1; dr <= 1; ++dr)
        {
          for (int8_t dc = -1; dc <= 1; ++dc)
          {
            const int8_t expanded_row = (int8_t)row + dr;
            const int8_t expanded_column = (int8_t)column + dc;
            if ((expanded_row >= 0) && (expanded_row < 16) &&
                (expanded_column >= 0) && (expanded_column < 16))
            {
              mask_set(next_mask, (uint8_t)expanded_row,
                       (uint8_t)expanded_column);
            }
          }
        }
      }
    }
    return;
  }

  if ((last_spatial_trigger_ms != 0U) &&
      ((now_ms - last_spatial_trigger_ms) < SPATIAL_ACTIVE_HOLD_MS))
  {
    memcpy(next_mask, active_mask, SPATIAL_MASK_BYTES);
  }
  else
  {
    build_sentinel_mask(next_mask);
  }
}

static void write_spatial_prefix(uint8_t *target,
                                 const uint8_t marker[4],
                                 uint32_t now_ms,
                                 const uint8_t *acc_wire_144,
                                 const uint8_t mask[SPATIAL_MASK_BYTES],
                                 uint16_t count)
{
  uint32_t offset = 0U;
  memcpy(target, marker, 4U);
  offset = 4U;
  put_u32(target, &offset, now_ms);
  put_u32(target, &offset, next_sequence++);
  memcpy(&target[offset], acc_wire_144, 96U);
  offset += 96U;
  memcpy(&target[offset], mask, SPATIAL_MASK_BYTES);
  offset += SPATIAL_MASK_BYTES;
  put_u16(target, &offset, count);
}

static uint16_t pack_spatial(uint8_t *target,
                             const uint16_t *fsr1,
                             const uint16_t *fsr2,
                             const uint8_t *acc_wire_144,
                             uint32_t now_ms)
{
  uint8_t next_mask[SPATIAL_MASK_BYTES];
  build_spatial_mask(next_mask, fsr1, fsr2, now_ms);
  const uint8_t mask_changed =
      (spatial_cache_valid == 0U) ||
      (memcmp(next_mask, active_mask, SPATIAL_MASK_BYTES) != 0U);
  const uint16_t sampled = mask_count(next_mask);

  uint16_t changed = 0U;
  if ((mask_changed == 0U) && (spatial_cache_valid != 0U))
  {
    for (uint16_t position = 0U; position < FSR_CELLS; ++position)
    {
      if (mask_get(next_mask, position) == 0U) { continue; }
      if (absolute_difference(fsr1[position], previous_fsr1[position]) >
          delta_threshold)
      {
        ++changed;
      }
      if (absolute_difference(fsr2[position], previous_fsr2[position]) >
          delta_threshold)
      {
        ++changed;
      }
    }
  }

  uint16_t length = 0U;
  if (mask_changed != 0U)
  {
    length = (uint16_t)(SPATIAL_PREFIX_BYTES + 4U * sampled);
    write_spatial_prefix(target, MAGIC_ESPF, now_ms, acc_wire_144,
                         next_mask, sampled);
    uint32_t offset = SPATIAL_PREFIX_BYTES;
    for (uint16_t position = 0U; position < FSR_CELLS; ++position)
    {
      if (mask_get(next_mask, position) == 0U) { continue; }
      put_u16(target, &offset, fsr1[position]);
      put_u16(target, &offset, fsr2[position]);
    }
  }
  else if (changed == 0U)
  {
    length = SPATIAL_HEARTBEAT_BYTES;
    uint32_t offset = 0U;
    memcpy(target, MAGIC_ESP0, 4U);
    offset = 4U;
    put_u32(target, &offset, now_ms);
    put_u32(target, &offset, next_sequence++);
  }
  else if (changed > SPATIAL_MAX_CHANGED_RECORDS)
  {
    /* The fixed Host SPI slot is 1188 B; resynchronise instead of truncating. */
    length = (uint16_t)(SPATIAL_PREFIX_BYTES + 4U * sampled);
    write_spatial_prefix(target, MAGIC_ESPF, now_ms, acc_wire_144,
                         next_mask, sampled);
    uint32_t offset = SPATIAL_PREFIX_BYTES;
    for (uint16_t position = 0U; position < FSR_CELLS; ++position)
    {
      if (mask_get(next_mask, position) == 0U) { continue; }
      put_u16(target, &offset, fsr1[position]);
      put_u16(target, &offset, fsr2[position]);
    }
  }
  else
  {
    length = (uint16_t)(SPATIAL_PREFIX_BYTES + 4U * changed);
    write_spatial_prefix(target, MAGIC_ESPD, now_ms, acc_wire_144,
                         next_mask, changed);
    uint32_t offset = SPATIAL_PREFIX_BYTES;
    for (uint8_t layer = 0U; layer < 2U; ++layer)
    {
      const uint16_t *current = (layer == 0U) ? fsr1 : fsr2;
      const uint16_t *previous = (layer == 0U) ? previous_fsr1 : previous_fsr2;
      for (uint8_t row = 0U; row < 16U; ++row)
      {
        for (uint8_t column = 0U; column < 16U; ++column)
        {
          const uint16_t position = (uint16_t)row * 16U + column;
          if ((mask_get(next_mask, position) == 0U) ||
              (absolute_difference(current[position], previous[position]) <=
               delta_threshold))
          {
            continue;
          }
          target[offset++] = (uint8_t)(((uint8_t)layer << 7U) | row);
          target[offset++] = column;
          put_u16(target, &offset, current[position]);
        }
      }
    }
  }

  memcpy(active_mask, next_mask, SPATIAL_MASK_BYTES);
  memcpy(previous_mask, next_mask, SPATIAL_MASK_BYTES);
  spatial_cache_valid = 1U;
  copy_current(fsr1, fsr2);
  return length;
}

void DataScalability_Init(void)
{
  memset(previous_fsr1, 0, sizeof(previous_fsr1));
  memset(previous_fsr2, 0, sizeof(previous_fsr2));
  memset(spatial_baseline1, 0, sizeof(spatial_baseline1));
  memset(spatial_baseline2, 0, sizeof(spatial_baseline2));
  memset(active_mask, 0, sizeof(active_mask));
  memset(previous_mask, 0, sizeof(previous_mask));
  mode = DATA_SCALABILITY_DEFAULT_MODE;
  delta_cache_valid = 0U;
  spatial_baseline_valid = 0U;
  spatial_cache_valid = 0U;
  delta_threshold = DELTA_DEFAULT_THRESHOLD;
  spatial_trigger_threshold = SPATIAL_DEFAULT_TRIGGER;
  next_sequence = 0U;
  cache_sequence = 0xFFFFFFFFU;
  last_spatial_trigger_ms = 0U;
  last_delta_full_sync_ms = 0U;
}

void DataScalability_SetMode(uint8_t requested_mode)
{
  if (requested_mode > DATA_SCALABILITY_MODE_SPATIAL) { return; }
  if (mode == requested_mode) { return; }
  mode = requested_mode;
  delta_cache_valid = 0U;
  spatial_cache_valid = 0U;
  spatial_baseline_valid = 0U;
  last_spatial_trigger_ms = 0U;
  last_delta_full_sync_ms = 0U;
}

uint8_t DataScalability_GetMode(void)
{
  return mode;
}

void DataScalability_ApplyCommand(const uint8_t *command, uint16_t length)
{
  if ((command == NULL) || (length < DATA_SCALABILITY_COMMAND_BYTES) ||
      (memcmp(command, COMMAND_MAGIC, 4U) != 0) || (command[4] != 1U))
  {
    return;
  }
  DataScalability_SetMode(command[5]);
  const uint16_t requested_delta = read_u16(&command[6]);
  const uint16_t requested_spatial = read_u16(&command[8]);
  if (requested_delta != 0U) { delta_threshold = requested_delta; }
  if (requested_spatial != 0U)
  {
    spatial_trigger_threshold = requested_spatial;
  }
}

uint16_t DataScalability_Encode(uint8_t *target,
                                const uint16_t *fsr1,
                                const uint16_t *fsr2,
                                const uint8_t *acc_wire_144,
                                uint32_t now_ms,
                                uint8_t base_flags)
{
  if ((target == NULL) || (fsr1 == NULL) || (fsr2 == NULL) ||
      (acc_wire_144 == NULL))
  {
    return 0U;
  }
  memset(target, 0, DATA_SCALABILITY_FRAME_BYTES);
  if (mode == DATA_SCALABILITY_MODE_DELTA)
  {
    return pack_esk_delta(target, fsr1, fsr2, acc_wire_144,
                          (uint8_t)(base_flags | FLAG_DELTA_FRAME), now_ms);
  }
  if (mode == DATA_SCALABILITY_MODE_SPATIAL)
  {
    return pack_spatial(target, fsr1, fsr2, acc_wire_144, now_ms);
  }
  return pack_esk_full(target, fsr1, fsr2, acc_wire_144, base_flags, now_ms);
}
