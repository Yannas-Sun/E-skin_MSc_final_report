#include "combined_acquisition.h"
#include "data_scalability_protocol.h"
#include "main.h"

#include <string.h>

extern SPI_HandleTypeDef hspi1;
extern SPI_HandleTypeDef hspi2;
extern SPI_HandleTypeDef hspi3;
extern void Combined_ReinitializeHostSPI(void);

#define FSR_ROWS 16U
#define FSR_COLS 16U
#define ACC_COUNT 9U

#define MAX11633_RESET_ALL 0x10U
#define MAX11633_SETUP 0x64U
#define MAX11633_SCAN_0_TO_15 0xF8U
#define ADC_TIMEOUT_MS 5U
#define FSR_MUX_SETTLE_US 100U
#define FSR_ROWS_PER_OUTPUT_FRAME FSR_ROWS

#define ACC_WHO_REG 0x0FU
#define ACC_WHO_EXPECTED 0x33U
#define ACC_CTRL1_REG 0x20U
#define ACC_CTRL4_REG 0x23U
#define ACC_OUT_X_L_REG 0x28U
#define ACC_CTRL1_VALUE 0x97U
#define ACC_CTRL4_VALUE 0x88U
#define ACC_READ 0x80U
#define ACC_INCREMENT 0x40U
#define ACC_TIMEOUT_MS 10U
#define ACC_SAMPLE_INTERVAL_MS 0U
#define ACC_HEALTH_SLOT_MS 100U

#define COMBINED_MAGIC_0 0x45U /* E */
#define COMBINED_MAGIC_1 0x53U /* S */
#define COMBINED_MAGIC_2 0x4BU /* K */
#define COMBINED_MAGIC_3 0x31U /* 1 */
#define COMBINED_VERSION 2U
#define COMBINED_FLAG_ACC_PRESENT 0x04U
#define COMBINED_FLAG_ROLLING_FSR 0x08U
#define COMBINED_FLAG_CRC_PRESENT 0x10U
#define CRC_FRAME_INTERVAL 32U
#define HEADER_BYTES 16U
#define FSR_BYTES (FSR_ROWS * FSR_COLS * 2U)
#define ACC_RECORD_BYTES 16U
#define ACC_BYTES (ACC_COUNT * ACC_RECORD_BYTES)
#define CRC_BYTES 4U
#define COMBINED_FRAME_BYTES (HEADER_BYTES + (2U * FSR_BYTES) + ACC_BYTES + CRC_BYTES)
#define HOST_TIMEOUT_MS 1500U
#define HOST_NSS_RELEASE_TIMEOUT_MS 10U

enum
{
  ACC_STATUS_OK = 0U,
  ACC_STATUS_BAD_ID = 1U,
  ACC_STATUS_SPI_ERROR = 2U,
  ACC_STATUS_CONFIG_ERROR = 3U,
  ACC_STATUS_DATA_ERROR = 4U
};

typedef struct
{
  uint8_t who;
  uint8_t status;
  int16_t x;
  int16_t y;
  int16_t z;
  uint8_t ctrl1;
  uint8_t ctrl4;
  uint16_t spi_error;
  uint8_t idle_miso;
  uint8_t command_rx;
  uint8_t ready;
} AccSample;

static uint16_t fsr1[FSR_ROWS][FSR_COLS];
static uint16_t fsr2[FSR_ROWS][FSR_COLS];
static AccSample acc[ACC_COUNT];
static uint8_t host_tx[2][COMBINED_FRAME_BYTES];
static uint8_t host_rx[2][COMBINED_FRAME_BYTES];
static uint8_t acc_wire_scratch[ACC_BYTES];
static uint8_t full_frame_scratch[COMBINED_FRAME_BYTES];
static uint32_t sequence;
static uint32_t last_acc_health_ms;
static uint32_t last_acc_sample_ms;
static uint8_t acc_health_cursor;
static uint8_t fsr_row_cursor;
static uint8_t last_fsr_row;
static uint8_t last_fsr_rows_updated;
static uint8_t host_send_index;
static uint8_t host_fill_index = 1U;
static uint8_t host_pipeline_primed;
static volatile uint8_t host_dma_complete;
static volatile uint8_t host_dma_error;
static volatile uint8_t host_dma_active;
static volatile uint32_t host_dma_complete_count;
static volatile uint32_t host_dma_error_count;
static volatile uint32_t host_dma_timeout_count;
static uint16_t profile_fsr_us;
static uint16_t profile_acc_us;
static uint16_t profile_pack_us;
static uint16_t profile_crc_us;
static uint16_t profile_dma_wait_us;
static uint32_t crc32_table[256];

static void delay_us(uint32_t microseconds)
{
  const uint32_t cycles_per_us = SystemCoreClock / 1000000U;
  const uint32_t cycles = cycles_per_us * microseconds;
  const uint32_t started = DWT->CYCCNT;
  while ((DWT->CYCCNT - started) < cycles) { __NOP(); }
}

static void delay_until_us(uint32_t started, uint32_t microseconds)
{
  const uint32_t cycles_per_us = SystemCoreClock / 1000000U;
  const uint32_t cycles = cycles_per_us * microseconds;
  while ((DWT->CYCCNT - started) < cycles) { __NOP(); }
}

static void delay_us_init(void)
{
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0U;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static uint16_t elapsed_us_saturated(uint32_t started)
{
  const uint32_t cycles_per_us = SystemCoreClock / 1000000U;
  const uint32_t elapsed = (DWT->CYCCNT - started) / cycles_per_us;
  return (elapsed > 0xFFFFU) ? 0xFFFFU : (uint16_t)elapsed;
}

static void put_u16(uint8_t *buffer, uint32_t *offset, uint16_t value)
{
  buffer[(*offset)++] = (uint8_t)value;
  buffer[(*offset)++] = (uint8_t)(value >> 8U);
}

static void put_u32(uint8_t *buffer, uint32_t *offset, uint32_t value)
{
  put_u16(buffer, offset, (uint16_t)value);
  put_u16(buffer, offset, (uint16_t)(value >> 16U));
}

static void crc32_init(void)
{
  for (uint32_t value = 0U; value < 256U; ++value)
  {
    uint32_t crc = value;
    for (uint8_t bit = 0U; bit < 8U; ++bit)
    {
      const uint32_t mask = (uint32_t)-(int32_t)(crc & 1U);
      crc = (crc >> 1U) ^ (0xEDB88320U & mask);
    }
    crc32_table[value] = crc;
  }
}

static uint32_t crc32_ieee(const uint8_t *data, uint32_t length)
{
  uint32_t crc = 0xFFFFFFFFU;
  for (uint32_t i = 0U; i < length; ++i)
  {
    crc = crc32_table[(crc ^ data[i]) & 0xFFU] ^ (crc >> 8U);
  }
  return ~crc;
}

static void select_mux(uint8_t channel)
{
  HAL_GPIO_WritePin(GPIOA, MUX_S0_Pin,
                    (channel & 0x01U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_S1_Pin,
                    (channel & 0x02U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_S2_Pin,
                    (channel & 0x04U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_S3_Pin,
                    (channel & 0x08U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static HAL_StatusTypeDef adc_init(uint16_t cs_pin)
{
  uint8_t command = MAX11633_RESET_ALL;
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_Transmit(&hspi1, &command, 1U, ADC_TIMEOUT_MS);
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }
  HAL_Delay(1U);
  command = MAX11633_SETUP;
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  status = HAL_SPI_Transmit(&hspi1, &command, 1U, ADC_TIMEOUT_MS);
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  HAL_Delay(1U);
  return status;
}

static HAL_StatusTypeDef adc_start_scan(uint16_t cs_pin)
{
  uint8_t command = MAX11633_SCAN_0_TO_15;
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_Transmit(&hspi1, &command, 1U, ADC_TIMEOUT_MS);
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  return status;
}

static HAL_StatusTypeDef adc_wait_eoc(uint16_t eoc_pin)
{
  const uint32_t start = HAL_GetTick();
  while (HAL_GPIO_ReadPin(GPIOB, eoc_pin) == GPIO_PIN_SET)
  {
    if ((HAL_GetTick() - start) >= ADC_TIMEOUT_MS)
    {
      return HAL_TIMEOUT;
    }
  }
  return HAL_OK;
}

static HAL_StatusTypeDef adc_read_results(uint16_t cs_pin,
                                          uint16_t samples[FSR_COLS])
{
  uint8_t rx[FSR_COLS * 2U] = {0U};
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_Receive(&hspi1, rx, sizeof(rx), ADC_TIMEOUT_MS);
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }
  for (uint8_t i = 0U; i < FSR_COLS; ++i)
  {
    samples[i] = (uint16_t)((((uint16_t)rx[2U * i] << 8U) |
                             rx[2U * i + 1U]) & 0x0FFFU);
  }
  return HAL_OK;
}

static uint8_t scan_fsr_rows(uint8_t row_count)
{
  uint16_t values1[FSR_COLS];
  uint16_t values2[FSR_COLS];
  uint8_t fsr1_ok = 1U;
  uint8_t fsr2_ok = 1U;
  uint8_t mux_already_settling = 0U;
  uint32_t mux_settle_started = 0U;
  last_fsr_rows_updated = row_count;

  /*
   * Both analogue MUXes share the same four address lines but have separate
   * enables and ADCs. Enable both after each address change, wait once, then
   * acquire both arrays. Both FSR layers keep the same MUX address order;
   * FSR2 stores the ADC channel as the first matrix index.
   */
  for (uint8_t row = 0U; row < row_count; ++row)
  {
    const uint8_t mux_address = fsr_row_cursor;
    last_fsr_row = mux_address;
    if (mux_already_settling == 0U)
    {
      select_mux(mux_address);
      HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_RESET);
      HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_RESET);
      mux_settle_started = DWT->CYCCNT;
    }
    delay_until_us(mux_settle_started, FSR_MUX_SETTLE_US);

    HAL_StatusTypeDef status1 = HAL_ERROR;
    HAL_StatusTypeDef status2 = HAL_ERROR;

    /* The ADCs have separate CS/EOC pins. Start both conversions before
     * waiting so their 16-channel conversion phases overlap. Commands and
     * FIFO reads remain sequential because both DOUT pins share SPI1 MISO. */
    if (fsr1_ok != 0U)
    {
      status1 = adc_start_scan(ADC_CS1_Pin);
    }
    if (fsr2_ok != 0U)
    {
      status2 = adc_start_scan(ADC_CS2_Pin);
    }
    if (status1 == HAL_OK)
    {
      status1 = adc_wait_eoc(ADC_EOC1_Pin);
    }
    if (status2 == HAL_OK)
    {
      status2 = adc_wait_eoc(ADC_EOC2_Pin);
    }

    /* Both conversions are now complete and their samples are held in the
     * ADC FIFOs. Start settling the next external MUX address before reading
     * those digital results, overlapping up to two 32-byte SPI1 reads with
     * the next address's analogue settling time. */
    HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_SET);
    if ((row + 1U) < row_count)
    {
      const uint8_t next_mux_address =
          (uint8_t)((mux_address + 1U) % FSR_ROWS);
      select_mux(next_mux_address);
      HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_RESET);
      HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_RESET);
      mux_settle_started = DWT->CYCCNT;
      mux_already_settling = 1U;
    }
    else
    {
      mux_already_settling = 0U;
    }

    if (status1 == HAL_OK)
    {
      status1 = adc_read_results(ADC_CS1_Pin, values1);
    }
    if (status2 == HAL_OK)
    {
      status2 = adc_read_results(ADC_CS2_Pin, values2);
    }

    if (status1 != HAL_OK)
    {
      fsr1_ok = 0U;
    }
    else
    {
      memcpy(fsr1[mux_address], values1, sizeof(values1));
    }

    if (status2 != HAL_OK)
    {
      fsr2_ok = 0U;
    }
    else
    {
      for (uint8_t adc_index = 0U; adc_index < FSR_COLS; ++adc_index)
      {
        fsr2[adc_index][mux_address] = values2[adc_index];
      }
    }

    fsr_row_cursor = (uint8_t)((fsr_row_cursor + 1U) % FSR_ROWS);
  }

  /* Keep the last valid rows when one acquisition fails. Clearing a complete
   * matrix would replace useful retained data with artificial zeros; the
   * per-frame FSR status bits still expose the failed scan. */
  return (uint8_t)((fsr1_ok != 0U ? 0x01U : 0U) |
                   (fsr2_ok != 0U ? 0x02U : 0U));
}

static void acc_deselect(void)
{
  HAL_GPIO_WritePin(ACC_ENABLE_GPIO_Port, ACC_ENABLE_Pin, GPIO_PIN_SET);
}

static void acc_select(uint8_t index)
{
  acc_deselect();
  HAL_GPIO_WritePin(ACC_ADDR0_GPIO_Port, ACC_ADDR0_Pin,
                    (index & 1U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR1_GPIO_Port, ACC_ADDR1_Pin,
                    (index & 2U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR2_GPIO_Port, ACC_ADDR2_Pin,
                    (index & 4U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR3_GPIO_Port, ACC_ADDR3_Pin,
                    (index & 8U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  for (volatile uint32_t delay = 0U; delay < 64U; ++delay) { __NOP(); }
  HAL_GPIO_WritePin(ACC_ENABLE_GPIO_Port, ACC_ENABLE_Pin, GPIO_PIN_RESET);
  for (volatile uint32_t delay = 0U; delay < 64U; ++delay) { __NOP(); }
}

static HAL_StatusTypeDef acc_transfer(uint8_t index, uint8_t *tx,
                                      uint8_t *rx, uint16_t size)
{
  acc_select(index);
  acc[index].idle_miso =
      (HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_14) == GPIO_PIN_SET) ? 1U : 0U;
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(&hspi2, tx, rx, size, ACC_TIMEOUT_MS);
  acc[index].command_rx = rx[0];
  acc[index].spi_error = (uint16_t)(HAL_SPI_GetError(&hspi2) & 0xFFFFU);
  acc_deselect();
  return status;
}

static HAL_StatusTypeDef acc_read_reg(uint8_t index, uint8_t reg,
                                      uint8_t *value)
{
  uint8_t tx[2] = {(uint8_t)(ACC_READ | (reg & 0x3FU)), 0U};
  uint8_t rx[2] = {0U};
  HAL_StatusTypeDef status = acc_transfer(index, tx, rx, sizeof(tx));
  if (status == HAL_OK) { *value = rx[1]; }
  return status;
}

static HAL_StatusTypeDef acc_write_reg(uint8_t index, uint8_t reg,
                                       uint8_t value)
{
  uint8_t tx[2] = {(uint8_t)(reg & 0x3FU), value};
  uint8_t rx[2] = {0U};
  return acc_transfer(index, tx, rx, sizeof(tx));
}

static HAL_StatusTypeDef acc_init_one(uint8_t index)
{
  uint8_t identity = 0U;
  acc[index].ready = 0U;
  if (acc_read_reg(index, ACC_WHO_REG, &identity) != HAL_OK)
  {
    acc[index].status = ACC_STATUS_SPI_ERROR;
    return HAL_ERROR;
  }
  acc[index].who = identity;
  if (identity != ACC_WHO_EXPECTED)
  {
    acc[index].status = ACC_STATUS_BAD_ID;
    return HAL_ERROR;
  }
  if ((acc_write_reg(index, ACC_CTRL1_REG, ACC_CTRL1_VALUE) != HAL_OK) ||
      (acc_write_reg(index, ACC_CTRL4_REG, ACC_CTRL4_VALUE) != HAL_OK))
  {
    acc[index].status = ACC_STATUS_CONFIG_ERROR;
    return HAL_ERROR;
  }
  HAL_Delay(2U);
  if ((acc_read_reg(index, ACC_CTRL1_REG, &acc[index].ctrl1) != HAL_OK) ||
      (acc_read_reg(index, ACC_CTRL4_REG, &acc[index].ctrl4) != HAL_OK) ||
      (acc[index].ctrl1 != ACC_CTRL1_VALUE) ||
      (acc[index].ctrl4 != ACC_CTRL4_VALUE))
  {
    acc[index].status = ACC_STATUS_CONFIG_ERROR;
    return HAL_ERROR;
  }
  acc[index].status = ACC_STATUS_OK;
  acc[index].ready = 1U;
  return HAL_OK;
}

static HAL_StatusTypeDef acc_read_axes(uint8_t index)
{
  uint8_t tx[7] = {(uint8_t)(ACC_READ | ACC_INCREMENT | ACC_OUT_X_L_REG),
                   0U, 0U, 0U, 0U, 0U, 0U};
  uint8_t rx[7] = {0U};
  HAL_StatusTypeDef status = acc_transfer(index, tx, rx, sizeof(tx));
  if (status != HAL_OK)
  {
    return status;
  }
  uint8_t all_zero = 1U;
  uint8_t all_ff = 1U;
  for (uint8_t i = 1U; i < 7U; ++i)
  {
    all_zero &= (rx[i] == 0U) ? 1U : 0U;
    all_ff &= (rx[i] == 0xFFU) ? 1U : 0U;
  }
  if ((all_zero != 0U) || (all_ff != 0U))
  {
    return HAL_ERROR;
  }
  acc[index].x = (int16_t)(((int16_t)(((uint16_t)rx[2] << 8U) | rx[1])) >> 4U);
  acc[index].y = (int16_t)(((int16_t)(((uint16_t)rx[4] << 8U) | rx[3])) >> 4U);
  acc[index].z = (int16_t)(((int16_t)(((uint16_t)rx[6] << 8U) | rx[5])) >> 4U);
  return HAL_OK;
}

static void scan_acc(void)
{
  const uint32_t now = HAL_GetTick();
  if ((now - last_acc_sample_ms) >= ACC_SAMPLE_INTERVAL_MS)
  {
    for (uint8_t index = 0U; index < ACC_COUNT; ++index)
    {
      if (acc[index].ready == 0U) { continue; }
      if (acc_read_axes(index) != HAL_OK)
      {
        acc[index].status = ACC_STATUS_DATA_ERROR;
        acc[index].ready = 0U;
        acc[index].x = acc[index].y = acc[index].z = 0;
      }
      else
      {
        acc[index].status = ACC_STATUS_OK;
      }
    }
    last_acc_sample_ms = now;
  }

  /*
   * WHO_AM_I is a health check, not sample data. Check or recover one device
   * every 100 ms so all nine devices are covered in about 0.9 s without
   * paying nine identity transactions on every acquisition frame.
   */
  if ((HAL_GetTick() - last_acc_health_ms) >= ACC_HEALTH_SLOT_MS)
  {
    const uint8_t index = acc_health_cursor;
    if (acc[index].ready == 0U)
    {
      (void)acc_init_one(index);
    }
    else
    {
      uint8_t identity = 0U;
      if ((acc_read_reg(index, ACC_WHO_REG, &identity) != HAL_OK) ||
          (identity != ACC_WHO_EXPECTED))
      {
        acc[index].who = identity;
        acc[index].status = (identity == ACC_WHO_EXPECTED) ?
                            ACC_STATUS_SPI_ERROR : ACC_STATUS_BAD_ID;
        acc[index].ready = 0U;
        acc[index].x = acc[index].y = acc[index].z = 0;
      }
    }
    acc_health_cursor = (uint8_t)((index + 1U) % ACC_COUNT);
    last_acc_health_ms = HAL_GetTick();
  }
}

static void pack_frame(uint8_t *target, uint8_t flags)
{
  const uint32_t pack_started = DWT->CYCCNT;
  const uint32_t frame_sequence = sequence++;
  const uint8_t crc_present =
      ((frame_sequence % CRC_FRAME_INTERVAL) == 0U) ? 1U : 0U;
  if (crc_present != 0U) { flags |= COMBINED_FLAG_CRC_PRESENT; }

  uint32_t offset = 0U;
  target[offset++] = COMBINED_MAGIC_0;
  target[offset++] = COMBINED_MAGIC_1;
  target[offset++] = COMBINED_MAGIC_2;
  target[offset++] = COMBINED_MAGIC_3;
  target[offset++] = COMBINED_VERSION;
  target[offset++] = flags;
  put_u16(target, &offset, COMBINED_FRAME_BYTES);
  put_u32(target, &offset, frame_sequence);
  put_u32(target, &offset, HAL_GetTick());

  /* STM32G4 is little-endian and the protocol stores FSR uint16 values in
   * little-endian order. The matrices are contiguous, so two block copies
   * preserve the wire format while avoiding 512 put_u16() function calls. */
  memcpy(&target[offset], fsr1, FSR_BYTES);
  offset += FSR_BYTES;
  memcpy(&target[offset], fsr2, FSR_BYTES);
  offset += FSR_BYTES;

  for (uint8_t i = 0U; i < ACC_COUNT; ++i)
  {
    target[offset++] = acc[i].who;
    target[offset++] = acc[i].status;
    put_u16(target, &offset, (uint16_t)acc[i].x);
    put_u16(target, &offset, (uint16_t)acc[i].y);
    put_u16(target, &offset, (uint16_t)acc[i].z);
    target[offset++] = acc[i].ctrl1;
    target[offset++] = acc[i].ctrl4;
    put_u16(target, &offset, acc[i].spi_error);
    target[offset++] = acc[i].idle_miso;
    target[offset++] = acc[i].command_rx;
    /* ACC record 0 describes FSR freshness: last MUX address and number of
     * addresses freshly scanned for this frame (16 in full-scan mode). */
    if (i == 0U)
    {
      target[offset++] = last_fsr_row;
      target[offset++] = last_fsr_rows_updated;
    }
    else
    {
      uint16_t profile = 0U;
      if (i == 1U) { profile = profile_fsr_us; }
      if (i == 2U) { profile = profile_acc_us; }
      if (i == 3U) { profile = profile_pack_us; }
      if (i == 4U) { profile = profile_dma_wait_us; }
      if (i == 5U) { profile = profile_crc_us; }
      put_u16(target, &offset, profile);
    }
  }
  profile_pack_us = elapsed_us_saturated(pack_started);

  const uint32_t crc_started = DWT->CYCCNT;
  const uint32_t crc = (crc_present != 0U) ? crc32_ieee(target, offset) : 0U;
  profile_crc_us = elapsed_us_saturated(crc_started);
  put_u32(target, &offset, crc);
}

static uint16_t pack_selected_frame(uint8_t *target, uint8_t flags)
{
  /* Reuse the validated ACC wire layout from the existing full-frame packer.
   * The new protocol encoder then chooses Full, Delta, or Spatial Sparse. */
  pack_frame(full_frame_scratch, flags);
  memcpy(acc_wire_scratch,
         &full_frame_scratch[HEADER_BYTES + (2U * FSR_BYTES)],
         ACC_BYTES);
  return DataScalability_Encode(target, &fsr1[0][0], &fsr2[0][0],
                                acc_wire_scratch, HAL_GetTick(), flags);
}

static HAL_StatusTypeDef start_frame_dma(uint8_t buffer_index)
{
  /* At 80 MHz the CPU can finish frame N+1 before the Teensy has completed
   * the 100 us CS hold for frame N. Never reset/re-arm SPI3 while hardware NSS
   * is still low; doing so exposed three stale FIFO bytes and alternating DMA
   * completion timeouts that the slower 16 MHz acquisition path had hidden. */
  const uint32_t nss_started = HAL_GetTick();
  while (HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15) == GPIO_PIN_RESET)
  {
    if ((HAL_GetTick() - nss_started) >= HOST_NSS_RELEASE_TIMEOUT_MS)
    {
      ++host_dma_timeout_count;
      return HAL_TIMEOUT;
    }
  }
  /* At 10 MHz, DMA completion precedes the master's physical NSS release by
   * only a few microseconds. Keep NSS high for a short stable interval before
   * resetting SPI3 so the peripheral fully closes the previous slave frame. */
  delay_us(50U);
  if (HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15) == GPIO_PIN_RESET)
  {
    ++host_dma_timeout_count;
    return HAL_BUSY;
  }

  /*
   * A repeated two-byte prefix before ESK1 showed that SPI3 retained stale TX
   * state between slave transactions. Reset the peripheral before publishing
   * HOST_IRQ so the first master clock always shifts host_tx[0].
   */
  (void)HAL_SPI_Abort(&hspi3);
  Combined_ReinitializeHostSPI();
  host_dma_complete = 0U;
  host_dma_error = 0U;
  host_dma_active = 0U;

  /* Arm both DMA directions before publishing HOST_IRQ. This guarantees that
   * TX can feed MISO and RX can drain every MOSI dummy byte before the Teensy
   * supplies the first SCK edge. */
  HAL_StatusTypeDef status = HAL_SPI_TransmitReceive_DMA(
      &hspi3, host_tx[buffer_index], host_rx[buffer_index],
      COMBINED_FRAME_BYTES);
  if (status != HAL_OK)
  {
    ++host_dma_error_count;
    return status;
  }

  host_dma_active = 1U;
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_SET);
  return HAL_OK;
}

static HAL_StatusTypeDef wait_frame_dma(void)
{
  const uint32_t started = HAL_GetTick();
  while ((host_dma_complete == 0U) && (host_dma_error == 0U) &&
         ((HAL_GetTick() - started) < HOST_TIMEOUT_MS))
  {
    __WFI();
  }
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
  host_dma_active = 0U;

  if (host_dma_complete != 0U)
  {
    return HAL_OK;
  }

  (void)HAL_SPI_Abort(&hspi3);
  if (host_dma_error != 0U)
  {
    return HAL_ERROR;
  }
  ++host_dma_timeout_count;
  return HAL_TIMEOUT;
}

void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef *hspi)
{
  if (hspi->Instance == SPI3)
  {
    host_dma_complete = 1U;
    host_dma_active = 0U;
    HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
    ++host_dma_complete_count;
  }
}

void HAL_SPI_ErrorCallback(SPI_HandleTypeDef *hspi)
{
  if (hspi->Instance == SPI3)
  {
    host_dma_error = 1U;
    host_dma_active = 0U;
    HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
    ++host_dma_error_count;
  }
}

void CombinedAcquisition_Init(void)
{
  GPIO_InitTypeDef gpio = {0};
  delay_us_init();
  crc32_init();
  DataScalability_Init();
  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin | ADC_CS2_Pin | MUX_EN2_Pin,
                    GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);

  gpio.Pin = ADC_CS2_Pin | MUX_EN2_Pin;
  gpio.Mode = GPIO_MODE_OUTPUT_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &gpio);
  gpio.Pin = ADC_EOC2_Pin;
  gpio.Mode = GPIO_MODE_INPUT;
  HAL_GPIO_Init(GPIOB, &gpio);

  acc_deselect();
  (void)adc_init(ADC_CS1_Pin);
  (void)adc_init(ADC_CS2_Pin);
  HAL_Delay(1000U);
  memset(acc, 0, sizeof(acc));
  for (uint8_t i = 0U; i < ACC_COUNT; ++i)
  {
    (void)acc_init_one(i);
  }
  last_acc_health_ms = HAL_GetTick();
  last_acc_sample_ms = HAL_GetTick() - ACC_SAMPLE_INTERVAL_MS;
}

void CombinedAcquisition_RunOnce(void)
{
  /* Prime the pipeline with one complete frame before starting the first DMA.
   * After that, host_send_index is immutable while DMA reads it and the CPU
   * acquires/packs only into host_fill_index. */
  if (host_pipeline_primed == 0U)
  {
    /* Fill every row before publishing the first full-scan frame. Steady state
     * also scans all 16 shared MUX addresses for every output frame. */
    uint32_t profile_started = DWT->CYCCNT;
    uint8_t flags = scan_fsr_rows(FSR_ROWS);
    profile_fsr_us = elapsed_us_saturated(profile_started);
    profile_started = DWT->CYCCNT;
    scan_acc();
    profile_acc_us = elapsed_us_saturated(profile_started);
    flags |= COMBINED_FLAG_ACC_PRESENT;
    (void)pack_selected_frame(host_tx[host_send_index], flags);
    host_pipeline_primed = 1U;
  }

  if (start_frame_dma(host_send_index) != HAL_OK)
  {
    HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
    (void)HAL_SPI_Abort(&hspi3);
    Combined_ReinitializeHostSPI();
    HAL_Delay(10U);
    return;
  }

  /* DMA sends frame N while the CPU acquires and packs frame N+1 into the
   * other buffer. Cortex-M4 has no data cache, so no cache maintenance is
   * required before swapping ownership. */
  uint32_t profile_started = DWT->CYCCNT;
  uint8_t flags = scan_fsr_rows(FSR_ROWS_PER_OUTPUT_FRAME);
  profile_fsr_us = elapsed_us_saturated(profile_started);
  profile_started = DWT->CYCCNT;
  scan_acc();
  profile_acc_us = elapsed_us_saturated(profile_started);
  flags |= COMBINED_FLAG_ACC_PRESENT;
  if (FSR_ROWS_PER_OUTPUT_FRAME < FSR_ROWS)
  {
    flags |= COMBINED_FLAG_ROLLING_FSR;
  }
  (void)pack_selected_frame(host_tx[host_fill_index], flags);

  profile_started = DWT->CYCCNT;
  const HAL_StatusTypeDef status = wait_frame_dma();
  profile_dma_wait_us = elapsed_us_saturated(profile_started);
  const uint8_t released_index = host_send_index;
  DataScalability_ApplyCommand(host_rx[released_index],
                               COMBINED_FRAME_BYTES);
  host_send_index = host_fill_index;
  host_fill_index = released_index;

  if (status != HAL_OK)
  {
    HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
    (void)HAL_SPI_Abort(&hspi3);
    Combined_ReinitializeHostSPI();
    HAL_Delay(10U);
  }
}
