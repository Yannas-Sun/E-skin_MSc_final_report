#include "combined_acquisition.h"
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
#ifndef SCLK33_SETUP_BYTE
#define SCLK33_SETUP_BYTE 0x74U
#endif
#define MAX11633_LEGACY_AVERAGING 0x31U
#define MAX11633_SCAN_0_TO_15 0xF8U
#define MAX11633_SCLK_TRANSFER_BYTES (1U + (FSR_COLS * 2U))
#define MAX11633_FIFO_BYTES (FSR_COLS * 2U)
#define ADC_TIMEOUT_MS 5U
#define FSR_ROWS_PER_OUTPUT_FRAME FSR_ROWS

/*
 * These values are supplied by the experiment CMake profile. The defaults
 * reproduce the old Teensy wire timing: SPI1 at 10 MHz and no explicit MUX
 * settling delay. "safe2p5" overrides both values before this file is built.
 */
#ifndef SCLK33_SPI_BAUDRATE_PRESCALER
#define SCLK33_SPI_BAUDRATE_PRESCALER SPI_BAUDRATEPRESCALER_8
#endif
#ifndef SCLK33_MUX_SETTLE_US
#define SCLK33_MUX_SETTLE_US 0U
#endif
#ifndef SCLK33_FSR_HZ
#define SCLK33_FSR_HZ 0U
#endif
#ifndef SCLK33_ACC_HZ
#define SCLK33_ACC_HZ 0U
#endif
#ifndef INTERNAL_FIFO_GAP_US
#define INTERNAL_FIFO_GAP_US 0U
#endif

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
#define ACC_HEALTH_SLOT_MS 100U

#define COMBINED_MAGIC_0 0x45U /* E */
#define COMBINED_MAGIC_1 0x53U /* S */
#define COMBINED_MAGIC_2 0x4BU /* K */
#define COMBINED_MAGIC_3 0x31U /* 1 */
#define COMBINED_VERSION 2U
#define COMBINED_FLAG_ACC_PRESENT 0x04U
#define COMBINED_FLAG_ROLLING_FSR 0x08U
#define COMBINED_FLAG_CRC_PRESENT 0x10U
#define COMBINED_FLAG_ADC_EXPERIMENT 0x20U
/* Set only when the corresponding sensor group was acquired for this frame.
 * When a custom rate is lower than the transport rate, the previous values are
 * retained and these flags make that intentional repetition visible. */
#define COMBINED_FLAG_FSR_UPDATED 0x40U
#define COMBINED_FLAG_ACC_UPDATED 0x80U
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
static uint32_t sequence;
static uint32_t last_acc_health_ms;
static uint8_t acc_health_cursor;
static uint8_t fsr_row_cursor;
static uint8_t last_fsr_row;
static uint8_t last_fsr_rows_updated;
static uint8_t fsr_last_flags;
static uint32_t fsr_last_update_cycles;
static uint32_t acc_last_update_cycles;
static uint8_t acquisition_schedule_started;
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
static uint8_t fsr_adc1_configured;
static uint8_t fsr_adc2_configured;
static DMA_HandleTypeDef hdma_spi1_rx;
static DMA_HandleTypeDef hdma_spi1_tx;
static volatile uint8_t adc_dma_complete;
static volatile uint8_t adc_dma_error;

#ifndef INTERNAL_FIFO_DMA_EXPERIMENT
static const uint8_t max11633_sclk_tx[MAX11633_SCLK_TRANSFER_BYTES] = {
    0x86U, 0x00U, 0x8EU, 0x00U, 0x96U, 0x00U, 0x9EU, 0x00U,
    0xA6U, 0x00U, 0xAEU, 0x00U, 0xB6U, 0x00U, 0xBEU, 0x00U,
    0xC6U, 0x00U, 0xCEU, 0x00U, 0xD6U, 0x00U, 0xDEU, 0x00U,
    0xE6U, 0x00U, 0xEEU, 0x00U, 0xF6U, 0x00U, 0xFEU, 0x00U,
    0x00U};

_Static_assert(sizeof(max11633_sclk_tx) == MAX11633_SCLK_TRANSFER_BYTES,
               "SCLK reproduction transaction must remain exactly 33 bytes");
#else
static const uint8_t max11633_fifo_tx[MAX11633_FIFO_BYTES] = {0U};

_Static_assert(sizeof(max11633_fifo_tx) == MAX11633_FIFO_BYTES,
               "Internal-clock FIFO read must remain exactly 32 bytes");
#endif

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

/* The acquisition rates are build-time targets. A value of zero means that
 * the group is refreshed on every output loop, preserving the original
 * full-rate behaviour. DWT cycle arithmetic is intentionally unsigned so the
 * comparison remains valid across the 32-bit counter wrap. If a requested rate
 * is faster than the output loop, the loop itself is the limiting rate. */
static uint8_t acquisition_rate_due(uint32_t now_cycles,
                                    uint32_t last_update_cycles,
                                    uint32_t target_hz)
{
  if (target_hz == 0U) { return 1U; }
  const uint32_t period_cycles = SystemCoreClock / target_hz;
  return (period_cycles == 0U ||
          (uint32_t)(now_cycles - last_update_cycles) >= period_cycles) ?
             1U : 0U;
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
  command = SCLK33_SETUP_BYTE;
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  status = HAL_SPI_Transmit(&hspi1, &command, 1U, ADC_TIMEOUT_MS);
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }
  HAL_Delay(1U);
#ifdef INTERNAL_FIFO_DMA_EXPERIMENT
  /* The internal-clock experiment uses the reset default AVG=1 and AVGON=0.
   * Do not inherit the old SCLK-mode averaging-register write. */
  return HAL_OK;
#else
  /* Preserve the old Teensy register byte. Bit AVGON is set in 0x31, but the
   * MAX11633 disables averaging whenever clock mode 11 is selected. */
  command = MAX11633_LEGACY_AVERAGING;
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  status = HAL_SPI_Transmit(&hspi1, &command, 1U, ADC_TIMEOUT_MS);
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  return status;
#endif
}

static HAL_StatusTypeDef adc_dma_init(void)
{
  __HAL_RCC_DMAMUX1_CLK_ENABLE();
  __HAL_RCC_DMA2_CLK_ENABLE();

  hdma_spi1_rx.Instance = DMA2_Channel1;
  hdma_spi1_rx.Init.Request = DMA_REQUEST_SPI1_RX;
  hdma_spi1_rx.Init.Direction = DMA_PERIPH_TO_MEMORY;
  hdma_spi1_rx.Init.PeriphInc = DMA_PINC_DISABLE;
  hdma_spi1_rx.Init.MemInc = DMA_MINC_ENABLE;
  hdma_spi1_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  hdma_spi1_rx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  hdma_spi1_rx.Init.Mode = DMA_NORMAL;
  hdma_spi1_rx.Init.Priority = DMA_PRIORITY_VERY_HIGH;
  if (HAL_DMA_Init(&hdma_spi1_rx) != HAL_OK)
  {
    return HAL_ERROR;
  }
  __HAL_LINKDMA(&hspi1, hdmarx, hdma_spi1_rx);

  hdma_spi1_tx.Instance = DMA2_Channel2;
  hdma_spi1_tx.Init.Request = DMA_REQUEST_SPI1_TX;
  hdma_spi1_tx.Init.Direction = DMA_MEMORY_TO_PERIPH;
  hdma_spi1_tx.Init.PeriphInc = DMA_PINC_DISABLE;
  hdma_spi1_tx.Init.MemInc = DMA_MINC_ENABLE;
  hdma_spi1_tx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  hdma_spi1_tx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  hdma_spi1_tx.Init.Mode = DMA_NORMAL;
  hdma_spi1_tx.Init.Priority = DMA_PRIORITY_VERY_HIGH;
  if (HAL_DMA_Init(&hdma_spi1_tx) != HAL_OK)
  {
    return HAL_ERROR;
  }
  __HAL_LINKDMA(&hspi1, hdmatx, hdma_spi1_tx);

  HAL_NVIC_SetPriority(DMA2_Channel1_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA2_Channel1_IRQn);
  HAL_NVIC_SetPriority(DMA2_Channel2_IRQn, 0, 1);
  HAL_NVIC_EnableIRQ(DMA2_Channel2_IRQn);
  return HAL_OK;
}

/*
 * Reproduce the previous Teensy fast_read_value() transaction exactly:
 *
 *   TX[0]       starts channel 0 with scan mode 11 (no automatic scan)
 *   TX[2..30]   starts channels 1..15 while the preceding LSB is returned
 *   RX[1..32]   contains sixteen big-endian 12-bit samples
 *
 * One CS-low window therefore contains 33 bytes / 264 SCK edges. EOC is not
 * read because SCLK itself drives acquisition and conversion in this mode.
 */
#ifndef INTERNAL_FIFO_DMA_EXPERIMENT
static HAL_StatusTypeDef adc_read16(uint16_t cs_pin,
                                    uint16_t samples[FSR_COLS])
{
  uint8_t rx[MAX11633_SCLK_TRANSFER_BYTES] = {0U};

  adc_dma_complete = 0U;
  adc_dma_error = 0U;
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status = HAL_SPI_TransmitReceive_DMA(
      &hspi1, max11633_sclk_tx, rx, sizeof(max11633_sclk_tx));
  if (status == HAL_OK)
  {
    const uint32_t started = HAL_GetTick();
    while ((adc_dma_complete == 0U) && (adc_dma_error == 0U) &&
           ((HAL_GetTick() - started) < ADC_TIMEOUT_MS))
    {
      __WFI();
    }
    if (adc_dma_complete == 0U)
    {
      (void)HAL_SPI_Abort(&hspi1);
      status = (adc_dma_error != 0U) ? HAL_ERROR : HAL_TIMEOUT;
    }
  }
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }
  for (uint8_t i = 0U; i < FSR_COLS; ++i)
  {
    samples[i] = (uint16_t)((((uint16_t)rx[1U + (2U * i)] << 8U) |
                             rx[2U + (2U * i)]) & 0x0FFFU);
  }
  return HAL_OK;
}
#else
/*
 * Internal-clock timing experiment requested for the MAX11633:
 *
 *   CS low:  0xF8 (automatic AIN0..AIN15 scan)
 *   CS high: conversion runs from the ADC's internal oscillator
 *   gap:     build-time INTERNAL_FIFO_GAP_US (0 = no deliberate wait)
 *   CS low:  32 dummy bytes clock the FIFO into SPI1 RX DMA
 *
 * At gap=0 the first FIFO SCLK follows as soon as the HAL command returns and
 * CS is toggled. This intentionally tests behaviour before EOC; it is an
 * experiment, not a claim that the sequence meets the data-sheet requirement.
 */
static HAL_StatusTypeDef adc_read16(uint16_t cs_pin,
                                    uint16_t samples[FSR_COLS])
{
  uint8_t command = MAX11633_SCAN_0_TO_15;
  uint8_t rx[MAX11633_FIFO_BYTES] = {0U};

  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_Transmit(&hspi1, &command, 1U, ADC_TIMEOUT_MS);
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }

  const uint32_t command_finished = DWT->CYCCNT;
  delay_until_us(command_finished, INTERNAL_FIFO_GAP_US);

  adc_dma_complete = 0U;
  adc_dma_error = 0U;
  HAL_GPIO_WritePin(GPIOB, cs_pin, GPIO_PIN_RESET);
  status = HAL_SPI_TransmitReceive_DMA(
      &hspi1, max11633_fifo_tx, rx, sizeof(max11633_fifo_tx));
  if (status == HAL_OK)
  {
    const uint32_t started = HAL_GetTick();
    while ((adc_dma_complete == 0U) && (adc_dma_error == 0U) &&
           ((HAL_GetTick() - started) < ADC_TIMEOUT_MS))
    {
      __WFI();
    }
    if (adc_dma_complete == 0U)
    {
      (void)HAL_SPI_Abort(&hspi1);
      status = (adc_dma_error != 0U) ? HAL_ERROR : HAL_TIMEOUT;
    }
  }
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
#endif

static uint8_t scan_fsr_rows(uint8_t row_count)
{
  uint16_t values1[FSR_COLS];
  uint16_t values2[FSR_COLS];
  uint8_t fsr1_ok = fsr_adc1_configured;
  uint8_t fsr2_ok = fsr_adc2_configured;
  uint8_t rows_updated_on_both_arrays = 0U;
  last_fsr_rows_updated = 0U;

  /* Enable both MUXes, select one shared address, then read ADC1 and ADC2
   * sequentially because their DOUT signals share SPI1 MISO. SCLK profiles use
   * one 33-byte transaction. The internal-clock profile uses a 1-byte scan
   * command followed by a separate 32-byte DMA FIFO read. FSR2 keeps the
   * current reversed/transposed map expected by the GUI. */
  for (uint8_t row = 0U; row < row_count; ++row)
  {
    const uint8_t mux_address = fsr_row_cursor;
    last_fsr_row = mux_address;
    HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_RESET);
    select_mux(mux_address);
    const uint32_t mux_selected = DWT->CYCCNT;
    delay_until_us(mux_selected, SCLK33_MUX_SETTLE_US);

    HAL_StatusTypeDef status1 = HAL_ERROR;
    HAL_StatusTypeDef status2 = HAL_ERROR;
    if (fsr1_ok != 0U)
    {
      status1 = adc_read16(ADC_CS1_Pin, values1);
    }
    if (fsr2_ok != 0U)
    {
      status2 = adc_read16(ADC_CS2_Pin, values2);
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
      const uint8_t mux_index = (uint8_t)(15U - mux_address);
      for (uint8_t adc_index = 0U; adc_index < FSR_COLS; ++adc_index)
      {
        fsr2[adc_index][mux_index] = values2[adc_index];
      }
    }

    if ((status1 == HAL_OK) && (status2 == HAL_OK))
    {
      ++rows_updated_on_both_arrays;
    }

    fsr_row_cursor = (uint8_t)((fsr_row_cursor + 1U) % FSR_ROWS);
  }

  last_fsr_rows_updated = rows_updated_on_both_arrays;

  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_SET);

  /* Keep the last valid rows when one acquisition fails. Clearing a complete
   * matrix would replace useful retained data with artificial zeros; the
   * per-frame FSR status bits still expose the failed scan. */
  return (uint8_t)(COMBINED_FLAG_ADC_EXPERIMENT |
                   (fsr1_ok != 0U ? 0x01U : 0U) |
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

static void scan_acc_samples(void)
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
}

static void service_acc_health(void)
{
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

/* Acquire the two sensor groups on independent schedules. The transport still
 * publishes a complete fixed-size frame every loop, so a group that is not due
 * keeps its previous matrix/axis values. The update flags and record-0 metadata
 * make the freshness of each frame explicit to the receiver. */
static uint8_t acquire_for_frame(uint8_t force_all)
{
  const uint32_t now_cycles = DWT->CYCCNT;
  const uint8_t fsr_due =
      (force_all != 0U) || (acquisition_schedule_started == 0U) ||
      acquisition_rate_due(now_cycles, fsr_last_update_cycles, SCLK33_FSR_HZ);
  const uint8_t acc_due =
      (force_all != 0U) || (acquisition_schedule_started == 0U) ||
      acquisition_rate_due(now_cycles, acc_last_update_cycles, SCLK33_ACC_HZ);
  uint8_t flags = fsr_last_flags | COMBINED_FLAG_ACC_PRESENT;

  if (fsr_due != 0U)
  {
    const uint32_t profile_started = DWT->CYCCNT;
    fsr_last_flags = scan_fsr_rows(FSR_ROWS_PER_OUTPUT_FRAME);
    profile_fsr_us = elapsed_us_saturated(profile_started);
    fsr_last_update_cycles = DWT->CYCCNT;
    flags = fsr_last_flags | COMBINED_FLAG_FSR_UPDATED |
            COMBINED_FLAG_ACC_PRESENT;
  }
  else
  {
    last_fsr_rows_updated = 0U;
    profile_fsr_us = 0U;
  }

  if (acc_due != 0U)
  {
    const uint32_t profile_started = DWT->CYCCNT;
    scan_acc_samples();
    profile_acc_us = elapsed_us_saturated(profile_started);
    acc_last_update_cycles = DWT->CYCCNT;
    flags |= COMBINED_FLAG_ACC_UPDATED;
  }
  else
  {
    profile_acc_us = 0U;
  }

  service_acc_health();
  if (FSR_ROWS_PER_OUTPUT_FRAME < FSR_ROWS)
  {
    flags |= COMBINED_FLAG_ROLLING_FSR;
  }
  if (force_all != 0U)
  {
    acquisition_schedule_started = 1U;
  }
  return flags;
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
  if (hspi->Instance == SPI1)
  {
    adc_dma_complete = 1U;
  }
  else if (hspi->Instance == SPI3)
  {
    host_dma_complete = 1U;
    host_dma_active = 0U;
    HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
    ++host_dma_complete_count;
  }
}

void HAL_SPI_ErrorCallback(SPI_HandleTypeDef *hspi)
{
  if (hspi->Instance == SPI1)
  {
    adc_dma_error = 1U;
  }
  else if (hspi->Instance == SPI3)
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

  /* main.c creates SPI1 in Mode 0. The experiment profile changes its
   * baud-rate prescaler before the two MAX11633 devices are configured. */
  hspi1.Init.BaudRatePrescaler = SCLK33_SPI_BAUDRATE_PRESCALER;
  const HAL_StatusTypeDef spi1_status = HAL_SPI_Init(&hspi1);
  const HAL_StatusTypeDef spi1_dma_status =
      (spi1_status == HAL_OK) ? adc_dma_init() : HAL_ERROR;

  acc_deselect();
  if ((spi1_status == HAL_OK) && (spi1_dma_status == HAL_OK))
  {
    fsr_adc1_configured =
        (adc_init(ADC_CS1_Pin) == HAL_OK) ? 1U : 0U;
    fsr_adc2_configured =
        (adc_init(ADC_CS2_Pin) == HAL_OK) ? 1U : 0U;
  }
  else
  {
    fsr_adc1_configured = 0U;
    fsr_adc2_configured = 0U;
  }
  HAL_Delay(1000U);
  memset(acc, 0, sizeof(acc));
  for (uint8_t i = 0U; i < ACC_COUNT; ++i)
  {
    (void)acc_init_one(i);
  }
  last_acc_health_ms = HAL_GetTick();
  fsr_last_flags = 0U;
  fsr_last_update_cycles = 0U;
  acc_last_update_cycles = 0U;
  acquisition_schedule_started = 0U;
}

void DMA2_Channel1_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&hdma_spi1_rx);
}

void DMA2_Channel2_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&hdma_spi1_tx);
}

void CombinedAcquisition_RunOnce(void)
{
  /* Prime the pipeline with one complete frame before starting the first DMA.
   * After that, host_send_index is immutable while DMA reads it and the CPU
   * acquires/packs only into host_fill_index. */
  if (host_pipeline_primed == 0U)
  {
    /* Always publish one fresh full frame before rate limiting begins. */
    const uint8_t flags = acquire_for_frame(1U);
    pack_frame(host_tx[host_send_index], flags);
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
  const uint8_t flags = acquire_for_frame(0U);
  pack_frame(host_tx[host_fill_index], flags);

  const uint32_t profile_started = DWT->CYCCNT;
  const HAL_StatusTypeDef status = wait_frame_dma();
  profile_dma_wait_us = elapsed_us_saturated(profile_started);
  const uint8_t released_index = host_send_index;
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
