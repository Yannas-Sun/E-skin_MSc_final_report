#include "combined_acquisition.h"
#include "data_scalability_protocol.h"
#include "main.h"

#include <string.h>

extern SPI_HandleTypeDef hspi1;
extern SPI_HandleTypeDef hspi3;
extern void Combined_ReinitializeHostSPI(void);

#define FSR_ROWS 16U
#define FSR_COLS 16U
#define MAX11633_RESET_ALL 0x10U
#define MAX11633_SETUP 0x64U
#define MAX11633_SCAN_0_TO_15 0xF8U
#define ADC_TIMEOUT_MS 5U
#ifndef FSR_MUX_SETTLE_US
#define FSR_MUX_SETTLE_US 100U
#endif
#define HOST_FRAME_BYTES DATA_SCALABILITY_FRAME_BYTES
#define HOST_COMMAND_BYTES DATA_SCALABILITY_COMMAND_BYTES
#define HOST_TIMEOUT_MS 1500U
#define HOST_NSS_RELEASE_TIMEOUT_MS 10U

static uint16_t fsr1[FSR_ROWS][FSR_COLS];
static uint16_t fsr2[FSR_ROWS][FSR_COLS];
static uint8_t host_tx[2][HOST_FRAME_BYTES];
static uint8_t host_rx[2][HOST_FRAME_BYTES];
static uint8_t host_send_index;
static uint8_t host_fill_index = 1U;
static uint8_t host_pipeline_primed;
static volatile uint8_t host_dma_complete;
static volatile uint8_t host_dma_error;
static volatile uint8_t host_dma_active;
static volatile uint32_t host_dma_timeout_count;
static volatile uint32_t host_dma_error_count;
static uint32_t last_scan_start_cycles;
static uint8_t scan_clock_started;
static uint8_t last_scan_status;

static uint8_t host_command_is_valid(const uint8_t *command)
{
  return (uint8_t)(command[0] == 'D' && command[1] == 'S' &&
                   command[2] == 'C' && command[3] == 'M' &&
                   command[4] == 2U);
}

static void delay_us_init(void)
{
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0U;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static void delay_us(uint32_t microseconds)
{
  const uint32_t cycles_per_us = SystemCoreClock / 1000000U;
  const uint32_t cycles = cycles_per_us * microseconds;
  const uint32_t started = DWT->CYCCNT;
  while ((DWT->CYCCNT - started) < cycles) { __NOP(); }
}

static void delay_until_cycles(uint32_t started, uint32_t microseconds)
{
  const uint32_t cycles_per_us = SystemCoreClock / 1000000U;
  const uint32_t cycles = cycles_per_us * microseconds;
  while ((DWT->CYCCNT - started) < cycles) { __NOP(); }
}

static void wait_for_requested_scan_period(void)
{
  const uint16_t requested_hz = DataScalability_GetScanRateHz();
  if (requested_hz == 0U)
  {
    scan_clock_started = 0U;
    return;
  }

  uint32_t period_cycles = SystemCoreClock / requested_hz;
  if (period_cycles == 0U) { period_cycles = 1U; }
  if (scan_clock_started != 0U)
  {
    while ((DWT->CYCCNT - last_scan_start_cycles) < period_cycles)
    {
      __NOP();
    }
  }
  last_scan_start_cycles = DWT->CYCCNT;
  scan_clock_started = 1U;
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
  if (status != HAL_OK) { return status; }
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
  const uint32_t started = HAL_GetTick();
  while (HAL_GPIO_ReadPin(GPIOB, eoc_pin) == GPIO_PIN_SET)
  {
    if ((HAL_GetTick() - started) >= ADC_TIMEOUT_MS) { return HAL_TIMEOUT; }
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
  if (status != HAL_OK) { return status; }

  for (uint8_t i = 0U; i < FSR_COLS; ++i)
  {
    samples[i] = (uint16_t)((((uint16_t)rx[2U * i] << 8U) |
                             rx[2U * i + 1U]) & 0x0FFFU);
  }
  return HAL_OK;
}

static uint8_t scan_fsr_rows(void)
{
  uint16_t values1[FSR_COLS];
  uint16_t values2[FSR_COLS];
  uint8_t fsr1_ok = 1U;
  uint8_t fsr2_ok = 1U;
  uint8_t mux_already_settling = 0U;
  uint32_t mux_settle_started = 0U;

  for (uint8_t row = 0U; row < FSR_ROWS; ++row)
  {
    if (mux_already_settling == 0U)
    {
      select_mux(row);
      HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_RESET);
      HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_RESET);
      mux_settle_started = DWT->CYCCNT;
    }
    delay_until_cycles(mux_settle_started, FSR_MUX_SETTLE_US);

    HAL_StatusTypeDef status1 = adc_start_scan(ADC_CS1_Pin);
    HAL_StatusTypeDef status2 = adc_start_scan(ADC_CS2_Pin);
    if (status1 == HAL_OK) { status1 = adc_wait_eoc(ADC_EOC1_Pin); }
    if (status2 == HAL_OK) { status2 = adc_wait_eoc(ADC_EOC2_Pin); }

    HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_SET);

    /* While the current ADC FIFOs are read over the shared SPI1 MISO line,
     * let the next analogue MUX address complete its settling interval. */
    const uint8_t next_mux = (uint8_t)(row + 1U);
    if (next_mux < FSR_ROWS)
    {
      select_mux(next_mux);
      HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_RESET);
      HAL_GPIO_WritePin(GPIOB, MUX_EN2_Pin, GPIO_PIN_RESET);
      mux_settle_started = DWT->CYCCNT;
      mux_already_settling = 1U;
    }
    else
    {
      mux_already_settling = 0U;
    }

    if (status1 == HAL_OK) { status1 = adc_read_results(ADC_CS1_Pin, values1); }
    if (status2 == HAL_OK) { status2 = adc_read_results(ADC_CS2_Pin, values2); }

    if (status1 != HAL_OK)
    {
      fsr1_ok = 0U;
    }
    else
    {
      memcpy(fsr1[row], values1, sizeof(values1));
    }

    if (status2 != HAL_OK)
    {
      fsr2_ok = 0U;
    }
    else
    {
      /* FSR2 keeps the same electronic MUX address order, but its physical
       * axes are exchanged: ADC channels are physical rows and the MUX
       * address is the physical column. Store it as [physical row][column]
       * so the protocol and GUI use the same R/C convention as FSR1. */
      for (uint8_t column = 0U; column < FSR_COLS; ++column)
      {
        fsr2[column][row] = values2[column];
      }
    }
  }

  return (uint8_t)((fsr1_ok != 0U ? 0x01U : 0U) |
                   (fsr2_ok != 0U ? 0x02U : 0U));
}

static HAL_StatusTypeDef start_frame_dma(uint8_t buffer_index)
{
  const uint32_t nss_started = HAL_GetTick();
  while (HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15) == GPIO_PIN_RESET)
  {
    if ((HAL_GetTick() - nss_started) >= HOST_NSS_RELEASE_TIMEOUT_MS)
    {
      ++host_dma_timeout_count;
      return HAL_TIMEOUT;
    }
  }
  delay_us(50U);
  if (HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_15) == GPIO_PIN_RESET)
  {
    ++host_dma_timeout_count;
    return HAL_BUSY;
  }

  (void)HAL_SPI_Abort(&hspi3);
  Combined_ReinitializeHostSPI();
  host_dma_complete = 0U;
  host_dma_error = 0U;
  host_dma_active = 0U;

  HAL_StatusTypeDef status = HAL_SPI_TransmitReceive_DMA(
      &hspi3, host_tx[buffer_index], host_rx[buffer_index], HOST_FRAME_BYTES);
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

  if (host_dma_complete != 0U) { return HAL_OK; }
  (void)HAL_SPI_Abort(&hspi3);
  if (host_dma_error != 0U) { return HAL_ERROR; }
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

static uint8_t acquire_and_encode(uint8_t *target)
{
  wait_for_requested_scan_period();
  const uint8_t status = scan_fsr_rows();
  last_scan_status = status;
  const uint16_t length = DataScalability_Encode(
      target, &fsr1[0][0], &fsr2[0][0], HAL_GetTick(), status);
  return (length != 0U) ? 1U : 0U;
}

void CombinedAcquisition_Init(void)
{
  GPIO_InitTypeDef gpio = {0};
  delay_us_init();
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

  (void)adc_init(ADC_CS1_Pin);
  (void)adc_init(ADC_CS2_Pin);
  memset(fsr1, 0, sizeof(fsr1));
  memset(fsr2, 0, sizeof(fsr2));
}

void CombinedAcquisition_RunOnce(void)
{
  if (host_pipeline_primed == 0U)
  {
    (void)acquire_and_encode(host_tx[host_send_index]);
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

  /* Acquire the next FSR frame while the previous fixed SPI slot is sent. */
  (void)acquire_and_encode(host_tx[host_fill_index]);

  const HAL_StatusTypeDef status = wait_frame_dma();
  const uint8_t released_index = host_send_index;
  host_send_index = host_fill_index;
  host_fill_index = released_index;

  if (status == HAL_OK)
  {
    const uint8_t command_valid =
        host_command_is_valid(host_rx[released_index]);
    const uint8_t command_flags = command_valid ?
        host_rx[released_index][12] : 0U;
    const uint8_t delta_resync_requested =
        (uint8_t)(command_valid != 0U &&
                  (command_flags & DATA_SCALABILITY_COMMAND_FLAG_DELTA_RESYNC) != 0U);
    const uint8_t spatial_resync_requested =
        (uint8_t)(command_valid != 0U &&
                  (command_flags & DATA_SCALABILITY_COMMAND_FLAG_SPATIAL_RESYNC) != 0U);
    const uint8_t mode_before = DataScalability_GetMode();
    DataScalability_ApplyCommand(host_rx[released_index], HOST_COMMAND_BYTES);
    if ((DataScalability_GetMode() != mode_before) ||
        (delta_resync_requested != 0U) ||
        (spatial_resync_requested != 0U))
    {
      /* Re-encode after a mode or cache-resync command. The sample in the
       * fill buffer was encoded before the command was received; without
       * this step, one stale Delta/Spatial frame could be sent before the
       * requested base frame. */
      (void)DataScalability_Encode(
          host_tx[host_send_index], &fsr1[0][0], &fsr2[0][0],
          HAL_GetTick(), last_scan_status);
    }
  }
  else
  {
    HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
    (void)HAL_SPI_Abort(&hspi3);
    Combined_ReinitializeHostSPI();
    HAL_Delay(10U);
  }
}
