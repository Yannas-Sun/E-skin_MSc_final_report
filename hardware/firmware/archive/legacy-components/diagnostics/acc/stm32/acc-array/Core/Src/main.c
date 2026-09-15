/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* Basic blocking acquisition and host-transfer implementation. */
#include <string.h>

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
SPI_HandleTypeDef hspi1;
SPI_HandleTypeDef hspi2;
SPI_HandleTypeDef hspi3;

/* USER CODE BEGIN PV */

/* FSR frame layout: [row][column], 12-bit ADC samples stored in 16 bits. */
#define FSR_ROWS             16U
#define FSR_COLUMNS          16U
#define MAX11633_EOC_TIMEOUT 5U
#define MAX11633_RESET_ALL   0x10U
#define MAX11633_SETUP       0x64U
#define MAX11633_SCAN_0_TO_15 0xF8U
#define HOST_FRAME_MAGIC     0xA5U
#define HOST_FRAME_BYTES     (1U + 2U + (FSR_ROWS * FSR_COLUMNS * 2U))
#define HOST_SPI_TIMEOUT     1000U
/*
 * Hardware-test mode follows the original ESKIN_STM32 acquisition path:
 * transmit the unmodified 12-bit MAX11633 result for every MUX/ADC cell.
 * Set this to 1U only after a new zero/full calibration has been captured.
 */
#define FSR_OUTPUT_NORMALIZED 0U

/* LIS2DH12/LIS3DH-compatible SPI register set. */
#define ACC_COUNT             9U
#define ACC_WHO_AM_I_REG      0x0FU
#define ACC_WHO_AM_I_EXPECTED 0x33U
#define ACC_CTRL_REG1         0x20U
#define ACC_CTRL_REG4         0x23U
#define ACC_OUT_X_L           0x28U
#define ACC_CTRL_REG1_100HZ   0x57U
#define ACC_CTRL_REG4_HR_BDU  0x88U
#define ACC_SPI_READ          0x80U
#define ACC_SPI_INCREMENT     0x40U
#define ACC_SPI_TIMEOUT       10U
#define ACC_POWER_UP_DELAY_MS 1000U
#define ACC_INIT_ATTEMPTS     5U
#define ACC_INIT_RETRY_DELAY_MS 20U
#define ACC_BACKGROUND_RETRY_MS 1000U

/*
 * Production build-time ACC selection supplied by CMake:
 *   0    stream all nine installed devices
 *   1..9 initialise, retry, read, and stream only that physical ACC
 */
#ifndef ACC_SELECTED
#define ACC_SELECTED 0
#endif
#if (ACC_SELECTED < 0) || (ACC_SELECTED > ACC_COUNT)
#error "ACC_SELECTED must be 0 (all) or 1..9 (single ACC)"
#endif
#if ACC_SELECTED == 0
#define ACC_TARGET_COUNT ACC_COUNT
#else
#define ACC_TARGET_COUNT 1U
#endif

enum
{
  ACC_STATUS_OK = 0U,
  ACC_STATUS_BAD_ID = 1U,
  ACC_STATUS_ID_SPI_ERROR = 2U,
  ACC_STATUS_CONFIG_ERROR = 3U,
  ACC_STATUS_DATA_SPI_ERROR = 4U
};

typedef enum
{
  FSR_STAGE_BOOT = 0U,
  FSR_STAGE_ADC_RESET,
  FSR_STAGE_ADC_SETUP,
  FSR_STAGE_MUX_SETTLE,
  FSR_STAGE_ADC_COMMAND,
  FSR_STAGE_ADC_EOC_WAIT,
  FSR_STAGE_ADC_READ,
  FSR_STAGE_ACC_SELECT,
  FSR_STAGE_ACC_ID,
  FSR_STAGE_ACC_CONFIG,
  FSR_STAGE_ACC_READ,
  FSR_STAGE_HOST_TRANSFER,
  FSR_STAGE_IDLE
} FSR_DiagnosticStage;

static uint16_t fsr_frame[FSR_ROWS][FSR_COLUMNS];
static uint8_t host_tx_frame[HOST_FRAME_BYTES];
static uint8_t host_rx_dummy[HOST_FRAME_BYTES];
static uint16_t host_sequence;
static volatile HAL_StatusTypeDef fsr_scan_status = HAL_OK;
static volatile FSR_DiagnosticStage fsr_stage = FSR_STAGE_BOOT;
static volatile FSR_DiagnosticStage fsr_last_error_stage = FSR_STAGE_BOOT;
static volatile uint8_t fsr_active_row;
static volatile uint32_t fsr_completed_scans;
static volatile uint32_t fsr_completed_frames;
static volatile uint32_t fsr_error_count;
static volatile uint32_t host_spi_error_code;
static volatile uint32_t host_spi_sr;
static volatile uint16_t host_spi_tx_remaining;
static volatile uint16_t host_spi_rx_remaining;
static uint8_t acc_who_am_i[ACC_COUNT];
static uint8_t acc_status[ACC_COUNT];
static uint8_t acc_ready[ACC_COUNT];
static uint8_t acc_idle_miso[ACC_COUNT];
static uint8_t acc_command_rx[ACC_COUNT];
static uint16_t acc_spi_error[ACC_COUNT];
static uint8_t acc_ctrl_reg1[ACC_COUNT];
static uint8_t acc_ctrl_reg4[ACC_COUNT];
static uint8_t acc_raw_axes[ACC_COUNT][6];
static volatile uint8_t acc_ready_count;
static volatile uint32_t acc_recovery_cycles;
static uint32_t acc_last_retry_tick;
static uint8_t acc_retry_cursor;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_SPI1_Init(void);
static void MX_SPI2_Init(void);
static void MX_SPI3_Init(void);
/* USER CODE BEGIN PFP */

static void MUX1_SelectRow(uint8_t row);
static HAL_StatusTypeDef MAX11633_Init(void);
static HAL_StatusTypeDef MAX11633_Read16(uint16_t *samples);
static uint16_t FSR_NormalizeSample(uint8_t row, uint8_t column,
                                    uint16_t raw_sample);
static HAL_StatusTypeDef FSR_ScanFrame(uint16_t frame[FSR_ROWS][FSR_COLUMNS]);
static HAL_StatusTypeDef HOST_SendFrame(const uint16_t frame[FSR_ROWS][FSR_COLUMNS]);
static void ACC_DeselectAll(void);
static uint8_t ACC_IsEnabled(uint8_t index);
static void ACC_Select(uint8_t index);
static HAL_StatusTypeDef ACC_ReadRegister(uint8_t index, uint8_t reg,
                                          uint8_t *value);
static HAL_StatusTypeDef ACC_WriteRegister(uint8_t index, uint8_t reg,
                                           uint8_t value);
static HAL_StatusTypeDef ACC_ReadAxes(uint8_t index, int16_t *x,
                                      int16_t *y, int16_t *z);
static HAL_StatusTypeDef ACC_InitOne(uint8_t index);
static HAL_StatusTypeDef ACC_InitAll(void);
static HAL_StatusTypeDef ACC_RetryFailed(void);
static HAL_StatusTypeDef ACC_ScanFrame(
    uint16_t frame[FSR_ROWS][FSR_COLUMNS]);
static void EnsureMainFlashBoot(void);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

static void EnsureMainFlashBoot(void)
{
  FLASH_OBProgramInitTypeDef option_bytes = {0};

  HAL_FLASHEx_OBGetConfig(&option_bytes);
  if (((option_bytes.USERConfig & FLASH_OPTR_nSWBOOT0) == 0U) &&
      ((option_bytes.USERConfig & FLASH_OPTR_nBOOT0) != 0U))
  {
    return;
  }

  /*
   * PB8 is shared by HOST_IRQ and the physical BOOT0 input. Select the nBOOT0
   * option bit instead of the pin, and set nBOOT0=1 so every reset starts from
   * main Flash. No protection, reset-mode, watchdog, or bank option is changed.
   */
  if (HAL_FLASH_Unlock() != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_FLASH_OB_Unlock() != HAL_OK)
  {
    (void)HAL_FLASH_Lock();
    Error_Handler();
  }

  option_bytes.OptionType = OPTIONBYTE_USER;
  option_bytes.USERType = OB_USER_nSWBOOT0 | OB_USER_nBOOT0;
  option_bytes.USERConfig = OB_BOOT0_FROM_OB | OB_nBOOT0_SET;

  if (HAL_FLASHEx_OBProgram(&option_bytes) != HAL_OK)
  {
    (void)HAL_FLASH_OB_Lock();
    (void)HAL_FLASH_Lock();
    Error_Handler();
  }

  /* Successful launch resets the MCU and reloads the new option bytes. */
  if (HAL_FLASH_OB_Launch() != HAL_OK)
  {
    (void)HAL_FLASH_OB_Lock();
    (void)HAL_FLASH_Lock();
    Error_Handler();
  }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  EnsureMainFlashBoot();

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_SPI1_Init();
  MX_SPI2_Init();
  MX_SPI3_Init();
  /* USER CODE BEGIN 2 */

  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  ACC_DeselectAll();
  /* Allow the ACC rail and every sensor's internal boot sequence to settle. */
  HAL_Delay(ACC_POWER_UP_DELAY_MS);
  (void)ACC_InitAll();
  acc_last_retry_tick = HAL_GetTick();
  /* Sensor validation is reported per row; it must not stop Host SPI frames. */
  fsr_scan_status = HAL_OK;

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    if ((acc_ready_count < ACC_TARGET_COUNT) &&
        ((HAL_GetTick() - acc_last_retry_tick) >= ACC_BACKGROUND_RETRY_MS))
    {
      (void)ACC_RetryFailed();
      acc_last_retry_tick = HAL_GetTick();
    }

    if (fsr_scan_status == HAL_OK)
    {
      fsr_scan_status = ACC_ScanFrame(fsr_frame);
      if (fsr_scan_status == HAL_OK)
      {
        ++fsr_completed_scans;
        fsr_scan_status = HOST_SendFrame(fsr_frame);
        if (fsr_scan_status == HAL_OK)
        {
          ++fsr_completed_frames;
          fsr_stage = FSR_STAGE_IDLE;
          /* Keep the ACC transport close to the established 25 frame/s rate. */
          HAL_Delay(35U);
        }
      }
    }
    else
    {
      /* Keep retrying after a missing ADC or host instead of stopping forever. */
      fsr_last_error_stage = fsr_stage;
      ++fsr_error_count;
      HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
      HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
      ACC_DeselectAll();
      (void)HAL_SPI_Abort(&hspi1);
      (void)HAL_SPI_Abort(&hspi2);
      (void)HAL_SPI_Abort(&hspi3);
      /*
       * A partial slave transaction can leave SPI3 misaligned even after an
       * abort. Reinitialise it so the following frame starts from byte zero.
       */
      (void)HAL_SPI_DeInit(&hspi3);
      MX_SPI3_Init();
      HAL_Delay(10U);
      (void)ACC_RetryFailed();
      acc_last_retry_tick = HAL_GetTick();
      fsr_scan_status = HAL_OK;
    }
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_2;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 7;
  hspi1.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * @brief SPI2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI2_Init(void)
{
  /*
   * Shared ACC bus: PB13=SCK, PB14=MISO, PB15=MOSI.
   * The CD74HC154 decoder generates the active-low sensor chip selects.
   */
  hspi2.Instance = SPI2;
  hspi2.Init.Mode = SPI_MODE_MASTER;
  hspi2.Init.Direction = SPI_DIRECTION_2LINES;
  hspi2.Init.DataSize = SPI_DATASIZE_8BIT;
  /*
   * LIS2DH12/LIS3DH stop SPC high while CS is inactive, drive data on the
   * falling edge, and require capture on the rising edge: SPI mode 3.
   */
  hspi2.Init.CLKPolarity = SPI_POLARITY_HIGH;
  hspi2.Init.CLKPhase = SPI_PHASE_2EDGE;
  hspi2.Init.NSS = SPI_NSS_SOFT;
  /*
   * Diagnostic rate: HSI/APB1 is 16 MHz, so /256 gives 62.5 kHz. This
   * deliberately slow clock separates protocol/pin faults from edge-quality
   * or long-FFC signal-integrity faults.
   */
  hspi2.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_256;
  hspi2.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi2.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi2.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi2.Init.CRCPolynomial = 7;
  hspi2.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi2.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  if (HAL_SPI_Init(&hspi2) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief SPI3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI3_Init(void)
{

  /* USER CODE BEGIN SPI3_Init 0 */

  /* USER CODE END SPI3_Init 0 */

  /* USER CODE BEGIN SPI3_Init 1 */

  /* USER CODE END SPI3_Init 1 */
  /* SPI3 parameter configuration*/
  hspi3.Instance = SPI3;
  hspi3.Init.Mode = SPI_MODE_SLAVE;
  hspi3.Init.Direction = SPI_DIRECTION_2LINES;
  hspi3.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi3.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi3.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi3.Init.NSS = SPI_NSS_HARD_INPUT;
  hspi3.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi3.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi3.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi3.Init.CRCPolynomial = 7;
  hspi3.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi3.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  if (HAL_SPI_Init(&hspi3) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI3_Init 2 */

  /* USER CODE END SPI3_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, MUX_S0_Pin|MUX_S1_Pin|MUX_S2_Pin|MUX_S3_Pin,
                    GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);

  /* Disable the ACC decoder before changing its address inputs. */
  HAL_GPIO_WritePin(ACC_ENABLE_GPIO_Port, ACC_ENABLE_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(ACC_ADDR0_GPIO_Port, ACC_ADDR0_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR1_GPIO_Port, ACC_ADDR1_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR2_GPIO_Port, ACC_ADDR2_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR3_GPIO_Port, ACC_ADDR3_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : MUX_S0_Pin MUX_S1_Pin MUX_S2_Pin MUX_S3_Pin
                           MUX_EN1_Pin */
  GPIO_InitStruct.Pin = MUX_S0_Pin|MUX_S1_Pin|MUX_S2_Pin|MUX_S3_Pin
                          |MUX_EN1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pins : ADC_CS1_Pin HOST_IRQ_Pin */
  GPIO_InitStruct.Pin = ADC_CS1_Pin|HOST_IRQ_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* Configure the CD74HC154 ACC decoder enable and four address inputs. */
  GPIO_InitStruct.Pin = ACC_ENABLE_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(ACC_ENABLE_GPIO_Port, &GPIO_InitStruct);

  GPIO_InitStruct.Pin = ACC_ADDR0_Pin;
  HAL_GPIO_Init(ACC_ADDR0_GPIO_Port, &GPIO_InitStruct);

  GPIO_InitStruct.Pin = ACC_ADDR1_Pin|ACC_ADDR2_Pin;
  HAL_GPIO_Init(GPIOF, &GPIO_InitStruct);

  GPIO_InitStruct.Pin = ACC_ADDR3_Pin;
  HAL_GPIO_Init(ACC_ADDR3_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : ADC_EOC1_Pin HOST_SYNC_Pin */
  GPIO_InitStruct.Pin = ADC_EOC1_Pin|HOST_SYNC_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

static void ACC_DeselectAll(void)
{
  /* CD74HC154 E0 is active low; high disables all sixteen nCS outputs. */
  HAL_GPIO_WritePin(ACC_ENABLE_GPIO_Port, ACC_ENABLE_Pin, GPIO_PIN_SET);
}

static uint8_t ACC_IsEnabled(uint8_t index)
{
#if ACC_SELECTED == 0
  return (index < ACC_COUNT) ? 1U : 0U;
#else
  return (index == (uint8_t)(ACC_SELECTED - 1U)) ? 1U : 0U;
#endif
}

static void ACC_Select(uint8_t index)
{
  ACC_DeselectAll();
  HAL_GPIO_WritePin(ACC_ADDR0_GPIO_Port, ACC_ADDR0_Pin,
                    (index & 0x01U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR1_GPIO_Port, ACC_ADDR1_Pin,
                    (index & 0x02U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR2_GPIO_Port, ACC_ADDR2_Pin,
                    (index & 0x04U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR3_GPIO_Port, ACC_ADDR3_Pin,
                    (index & 0x08U) ? GPIO_PIN_SET : GPIO_PIN_RESET);

  /* Allow the decoder address to settle before asserting the selected nCS. */
  for (volatile uint32_t delay = 0U; delay < 64U; ++delay)
  {
    __NOP();
  }
  HAL_GPIO_WritePin(ACC_ENABLE_GPIO_Port, ACC_ENABLE_Pin, GPIO_PIN_RESET);
  for (volatile uint32_t delay = 0U; delay < 64U; ++delay)
  {
    __NOP();
  }
}

static HAL_StatusTypeDef ACC_ReadRegister(uint8_t index, uint8_t reg,
                                          uint8_t *value)
{
  uint8_t tx[2] = {(uint8_t)(ACC_SPI_READ | (reg & 0x3FU)), 0U};
  uint8_t rx[2] = {0U, 0U};

  fsr_stage = FSR_STAGE_ACC_SELECT;
  ACC_Select(index);
  acc_idle_miso[index] =
      (HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_14) == GPIO_PIN_SET) ? 1U : 0U;
  fsr_stage = FSR_STAGE_ACC_ID;
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(&hspi2, tx, rx, sizeof(tx), ACC_SPI_TIMEOUT);
  acc_command_rx[index] = rx[0];
  acc_spi_error[index] = (uint16_t)(HAL_SPI_GetError(&hspi2) & 0x0FFFU);
  ACC_DeselectAll();
  if (status == HAL_OK)
  {
    *value = rx[1];
  }
  return status;
}

static HAL_StatusTypeDef ACC_WriteRegister(uint8_t index, uint8_t reg,
                                           uint8_t value)
{
  uint8_t tx[2] = {(uint8_t)(reg & 0x3FU), value};
  uint8_t rx[2] = {0U, 0U};

  fsr_stage = FSR_STAGE_ACC_SELECT;
  ACC_Select(index);
  fsr_stage = FSR_STAGE_ACC_CONFIG;
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(&hspi2, tx, rx, sizeof(tx), ACC_SPI_TIMEOUT);
  ACC_DeselectAll();
  return status;
}

static HAL_StatusTypeDef ACC_ReadAxes(uint8_t index, int16_t *x,
                                      int16_t *y, int16_t *z)
{
  uint8_t tx[7] = {
      (uint8_t)(ACC_SPI_READ | ACC_SPI_INCREMENT | ACC_OUT_X_L),
      0U, 0U, 0U, 0U, 0U, 0U};
  uint8_t rx[7] = {0U};

  fsr_stage = FSR_STAGE_ACC_SELECT;
  ACC_Select(index);
  fsr_stage = FSR_STAGE_ACC_READ;
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(&hspi2, tx, rx, sizeof(tx), ACC_SPI_TIMEOUT);
  ACC_DeselectAll();
  if (status != HAL_OK)
  {
    return status;
  }

  memcpy(acc_raw_axes[index], &rx[1], sizeof(acc_raw_axes[index]));

  /*
   * CTRL_REG4.HR=1 selects the 12-bit high-resolution output. The device
   * returns signed, left-justified little-endian values; shift by four to
   * obtain approximately 1 mg/count at the +/-2 g full scale.
   */
  *x = (int16_t)(((int16_t)((uint16_t)rx[2] << 8U | rx[1])) >> 4U);
  *y = (int16_t)(((int16_t)((uint16_t)rx[4] << 8U | rx[3])) >> 4U);
  *z = (int16_t)(((int16_t)((uint16_t)rx[6] << 8U | rx[5])) >> 4U);
  return HAL_OK;
}

static HAL_StatusTypeDef ACC_InitOne(uint8_t index)
{
  acc_who_am_i[index] = 0U;
  acc_status[index] = ACC_STATUS_ID_SPI_ERROR;
  acc_ready[index] = 0U;
  acc_idle_miso[index] = 0U;
  acc_command_rx[index] = 0U;
  acc_spi_error[index] = 0U;
  acc_ctrl_reg1[index] = 0U;
  acc_ctrl_reg4[index] = 0U;
  memset(acc_raw_axes[index], 0, sizeof(acc_raw_axes[index]));

  for (uint8_t attempt = 0U; attempt < ACC_INIT_ATTEMPTS; ++attempt)
  {
    uint8_t identity = 0U;
    ACC_DeselectAll();
    HAL_Delay(ACC_INIT_RETRY_DELAY_MS);

    if (ACC_ReadRegister(index, ACC_WHO_AM_I_REG, &identity) != HAL_OK)
    {
      acc_status[index] = ACC_STATUS_ID_SPI_ERROR;
      continue;
    }

    acc_who_am_i[index] = identity;
    if (identity != ACC_WHO_AM_I_EXPECTED)
    {
      acc_status[index] = ACC_STATUS_BAD_ID;
      continue;
    }

    if (ACC_WriteRegister(index, ACC_CTRL_REG1, ACC_CTRL_REG1_100HZ) !=
        HAL_OK)
    {
      acc_status[index] = ACC_STATUS_CONFIG_ERROR;
      continue;
    }
    HAL_Delay(2U);
    if (ACC_WriteRegister(index, ACC_CTRL_REG4, ACC_CTRL_REG4_HR_BDU) !=
        HAL_OK)
    {
      acc_status[index] = ACC_STATUS_CONFIG_ERROR;
      continue;
    }
    HAL_Delay(2U);

    if ((ACC_ReadRegister(index, ACC_CTRL_REG1, &acc_ctrl_reg1[index]) !=
         HAL_OK) ||
        (ACC_ReadRegister(index, ACC_CTRL_REG4, &acc_ctrl_reg4[index]) !=
         HAL_OK) ||
        (acc_ctrl_reg1[index] != ACC_CTRL_REG1_100HZ) ||
        (acc_ctrl_reg4[index] != ACC_CTRL_REG4_HR_BDU))
    {
      acc_status[index] = ACC_STATUS_CONFIG_ERROR;
      continue;
    }

    acc_status[index] = ACC_STATUS_OK;
    acc_ready[index] = 1U;
    ACC_DeselectAll();
    return HAL_OK;
  }

  ACC_DeselectAll();
  return HAL_ERROR;
}

static HAL_StatusTypeDef ACC_InitAll(void)
{
  memset(acc_who_am_i, 0, sizeof(acc_who_am_i));
  memset(acc_status, ACC_STATUS_ID_SPI_ERROR, sizeof(acc_status));
  memset(acc_ready, 0, sizeof(acc_ready));
  memset(acc_idle_miso, 0, sizeof(acc_idle_miso));
  memset(acc_command_rx, 0, sizeof(acc_command_rx));
  memset(acc_spi_error, 0, sizeof(acc_spi_error));
  memset(acc_ctrl_reg1, 0, sizeof(acc_ctrl_reg1));
  memset(acc_ctrl_reg4, 0, sizeof(acc_ctrl_reg4));
  memset(acc_raw_axes, 0, sizeof(acc_raw_axes));
  acc_ready_count = 0U;
  ACC_DeselectAll();

  for (uint8_t index = 0U; index < ACC_COUNT; ++index)
  {
    if (ACC_IsEnabled(index) == 0U)
    {
      continue;
    }
    if (ACC_InitOne(index) == HAL_OK)
    {
      ++acc_ready_count;
    }
  }

  ACC_DeselectAll();
  HAL_Delay(20U);
  return (acc_ready_count == ACC_TARGET_COUNT) ? HAL_OK : HAL_ERROR;
}

static HAL_StatusTypeDef ACC_RetryFailed(void)
{
  uint8_t ready_count = 0U;

  ++acc_recovery_cycles;
  /* Retry one failed device per cycle so recovery cannot collapse frame rate. */
  for (uint8_t offset = 0U; offset < ACC_COUNT; ++offset)
  {
    const uint8_t index = (uint8_t)((acc_retry_cursor + offset) % ACC_COUNT);
    if ((ACC_IsEnabled(index) != 0U) && (acc_ready[index] == 0U))
    {
      (void)ACC_InitOne(index);
      acc_retry_cursor = (uint8_t)((index + 1U) % ACC_COUNT);
      break;
    }
  }

  for (uint8_t index = 0U; index < ACC_COUNT; ++index)
  {
    if (ACC_IsEnabled(index) != 0U)
    {
      ready_count += (acc_ready[index] != 0U) ? 1U : 0U;
    }
  }
  acc_ready_count = ready_count;
  ACC_DeselectAll();
  return (ready_count == ACC_TARGET_COUNT) ? HAL_OK : HAL_ERROR;
}

static HAL_StatusTypeDef ACC_ScanFrame(
    uint16_t frame[FSR_ROWS][FSR_COLUMNS])
{
  memset(frame, 0, sizeof(uint16_t) * FSR_ROWS * FSR_COLUMNS);

  for (uint8_t index = 0U; index < ACC_COUNT; ++index)
  {
    int16_t x = 0;
    int16_t y = 0;
    int16_t z = 0;

    if (ACC_IsEnabled(index) == 0U)
    {
      continue;
    }
    fsr_active_row = index;

    frame[index][0] = acc_who_am_i[index];
    frame[index][1] = acc_status[index];
    frame[index][5] = acc_idle_miso[index];
    frame[index][6] = acc_command_rx[index];
    frame[index][7] = acc_spi_error[index];
    frame[index][8] = acc_ctrl_reg1[index];
    frame[index][9] = acc_ctrl_reg4[index];
    if (acc_ready[index] != 0U)
    {
      if (ACC_ReadAxes(index, &x, &y, &z) == HAL_OK)
      {
        acc_status[index] = ACC_STATUS_OK;
        frame[index][2] = (uint16_t)x;
        frame[index][3] = (uint16_t)y;
        frame[index][4] = (uint16_t)z;
      }
      else
      {
        acc_status[index] = ACC_STATUS_DATA_SPI_ERROR;
        acc_ready[index] = 0U;
        memset(acc_raw_axes[index], 0, sizeof(acc_raw_axes[index]));
        if (acc_ready_count > 0U)
        {
          --acc_ready_count;
        }
      }
      frame[index][1] = acc_status[index];
    }
    for (uint8_t raw_index = 0U; raw_index < 6U; ++raw_index)
    {
      frame[index][10U + raw_index] = acc_raw_axes[index][raw_index];
    }
  }
  return HAL_OK;
}

static uint16_t FSR_NormalizeSample(uint8_t row, uint8_t column,
                                    uint16_t raw_sample)
{
#if FSR_OUTPUT_NORMALIZED && FSR_MCU_CALIBRATION_VALID
  const int32_t zero = (int32_t)fsr_mcu_zero[row][column];
  const int32_t full = (int32_t)fsr_mcu_full[row][column];
  const int32_t span = full - zero;
  int32_t numerator;
  int32_t denominator;
  int32_t normalized;

  if (span >= (int32_t)FSR_MCU_CALIBRATION_MIN_SPAN)
  {
    numerator = (int32_t)raw_sample - zero;
    denominator = span;
  }
  else if (span <= -(int32_t)FSR_MCU_CALIBRATION_MIN_SPAN)
  {
    numerator = zero - (int32_t)raw_sample;
    denominator = -span;
  }
  else
  {
    /* An unresponsive calibration cell is transmitted as zero pressure. */
    return 0U;
  }

  if (numerator <= 0)
  {
    return 0U;
  }
  if (numerator >= denominator)
  {
    return 0x0FFFU;
  }

  /* Round to the nearest 12-bit code instead of truncating downward. */
  normalized = ((numerator * 0x0FFF) + (denominator / 2)) / denominator;
  if (normalized < 0)
  {
    return 0U;
  }
  if (normalized > 0x0FFF)
  {
    return 0x0FFFU;
  }
  return (uint16_t)normalized;
#else
  (void)row;
  (void)column;
  return raw_sample & 0x0FFFU;
#endif
}

static void MUX1_SelectRow(uint8_t row)
{
  HAL_GPIO_WritePin(GPIOA, MUX_S0_Pin, (row & 0x01U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_S1_Pin, (row & 0x02U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_S2_Pin, (row & 0x04U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_S3_Pin, (row & 0x08U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static HAL_StatusTypeDef MAX11633_Init(void)
{
  const uint8_t reset_command = MAX11633_RESET_ALL;
  const uint8_t setup_command = MAX11633_SETUP;
  HAL_StatusTypeDef status;

  /*
   * Reset all ADC registers first so a previous interrupted transaction or
   * firmware image cannot leave a stale scan/clock configuration behind.
   */
  fsr_stage = FSR_STAGE_ADC_RESET;
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_RESET);
  status = HAL_SPI_Transmit(&hspi1, (uint8_t *)&reset_command, 1U,
                            MAX11633_EOC_TIMEOUT);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }
  HAL_Delay(1U);

  /*
   * 0x64 selects internal clock mode 10 and the external reference input.
   * On mainboard revision 2.2, MAX11633 REF and VDD are tied to +3.3 V.
   */
  fsr_stage = FSR_STAGE_ADC_SETUP;
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_RESET);
  status = HAL_SPI_Transmit(&hspi1, (uint8_t *)&setup_command, 1U,
                            MAX11633_EOC_TIMEOUT);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  if (status == HAL_OK)
  {
    /* Allow the external reference path and analog front end to settle. */
    HAL_Delay(1U);
    fsr_stage = FSR_STAGE_IDLE;
  }
  return status;
}

static HAL_StatusTypeDef MAX11633_Read16(uint16_t *samples)
{
  uint8_t conversion_command = MAX11633_SCAN_0_TO_15;
  uint8_t rx[FSR_COLUMNS * 2U] = {0};
  HAL_StatusTypeDef status;
  uint32_t start;

  /* 0xF8 requests one conversion each from AIN0 through AIN15. */
  fsr_stage = FSR_STAGE_ADC_COMMAND;
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_RESET);
  status = HAL_SPI_Transmit(&hspi1, &conversion_command, 1U,
                            MAX11633_EOC_TIMEOUT);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }

  /* EOC is active low after the requested scan is complete. */
  fsr_stage = FSR_STAGE_ADC_EOC_WAIT;
  start = HAL_GetTick();
  while (HAL_GPIO_ReadPin(GPIOB, ADC_EOC1_Pin) == GPIO_PIN_SET)
  {
    if ((HAL_GetTick() - start) >= MAX11633_EOC_TIMEOUT)
    {
      return HAL_TIMEOUT;
    }
  }

  fsr_stage = FSR_STAGE_ADC_READ;
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_RESET);
  status = HAL_SPI_Receive(&hspi1, rx, sizeof(rx), MAX11633_EOC_TIMEOUT);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }

  for (uint32_t column = 0U; column < FSR_COLUMNS; ++column)
  {
    /* MAX11633 returns 12-bit binary results with four leading zero bits. */
    samples[column] = (uint16_t)(((uint16_t)rx[2U * column] << 8U) |
                                 rx[2U * column + 1U]);
    samples[column] &= 0x0FFFU;
  }
  return HAL_OK;
}

static HAL_StatusTypeDef FSR_ScanFrame(uint16_t frame[FSR_ROWS][FSR_COLUMNS])
{
  HAL_StatusTypeDef status;
  uint16_t raw_samples[FSR_COLUMNS];

  for (uint8_t row = 0U; row < FSR_ROWS; ++row)
  {
    fsr_active_row = row;
    MUX1_SelectRow(row);
    HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_RESET);
    fsr_stage = FSR_STAGE_MUX_SETTLE;
    HAL_Delay(1U); /* Settle after the active-low MUX has connected the row. */

    status = MAX11633_Read16(raw_samples);
    HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
    if (status != HAL_OK)
    {
      return status;
    }

    for (uint8_t column = 0U; column < FSR_COLUMNS; ++column)
    {
      frame[row][column] =
          FSR_NormalizeSample(row, column, raw_samples[column]);
    }
  }
  return HAL_OK;
}

static HAL_StatusTypeDef HOST_SendFrame(const uint16_t frame[FSR_ROWS][FSR_COLUMNS])
{
  uint32_t offset = 0U;
  HAL_StatusTypeDef status;

  host_tx_frame[offset++] = HOST_FRAME_MAGIC;
  host_tx_frame[offset++] = (uint8_t)(host_sequence & 0xFFU);
  host_tx_frame[offset++] = (uint8_t)(host_sequence >> 8U);
  ++host_sequence;

  for (uint32_t row = 0U; row < FSR_ROWS; ++row)
  {
    for (uint32_t column = 0U; column < FSR_COLUMNS; ++column)
    {
      const uint16_t sample = frame[row][column] & 0x0FFFU;
      host_tx_frame[offset++] = (uint8_t)(sample & 0xFFU);
      host_tx_frame[offset++] = (uint8_t)(sample >> 8U);
    }
  }

  /*
   * SPI3 is configured as a two-line slave, so every MISO byte transmitted also
   * receives a Teensy dummy byte on MOSI. Drain those bytes explicitly. Using
   * HAL_SPI_Transmit() here can leave RX FIFO data pending; the STM32G4 HAL then
   * waits for FRLVL_EMPTY until HOST_SPI_TIMEOUT even though Teensy already
   * received a valid frame.
   */
  fsr_stage = FSR_STAGE_HOST_TRANSFER;
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_SET);
  status = HAL_SPI_TransmitReceive(&hspi3, host_tx_frame, host_rx_dummy,
                                   HOST_FRAME_BYTES, HOST_SPI_TIMEOUT);
  host_spi_error_code = hspi3.ErrorCode;
  host_spi_sr = hspi3.Instance->SR;
  host_spi_tx_remaining = hspi3.TxXferCount;
  host_spi_rx_remaining = hspi3.RxXferCount;
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
  return status;
}

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
