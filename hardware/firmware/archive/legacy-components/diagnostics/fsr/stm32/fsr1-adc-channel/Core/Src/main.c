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
SPI_HandleTypeDef hspi3;

/* USER CODE BEGIN PV */

/* Live test: read AIN10 while stepping through all 16 MUX1 positions. */
#define MUX_CHANNELS         16U
#define TEST_ADC_CHANNEL     10U
#define MUX_STEP_PERIOD_MS   1000U
#define MAX11633_EOC_TIMEOUT 5U
#define MAX11633_RESET_ALL   0x10U
#define MAX11633_SETUP       0x64U
#define MAX11633_SINGLE_BASE 0x86U
#define HOST_FRAME_MAGIC     0xA7U
#define HOST_FRAME_BYTES     8U
#define HOST_SPI_TIMEOUT     1000U

typedef enum
{
  FSR_STAGE_BOOT = 0U,
  FSR_STAGE_ADC_RESET,
  FSR_STAGE_ADC_SETUP,
  FSR_STAGE_MUX_SETTLE,
  FSR_STAGE_ADC_COMMAND,
  FSR_STAGE_ADC_EOC_WAIT,
  FSR_STAGE_ADC_READ,
  FSR_STAGE_HOST_TRANSFER,
  FSR_STAGE_IDLE
} FSR_DiagnosticStage;

static uint16_t adc_test_sample;
static uint8_t host_tx_frame[HOST_FRAME_BYTES];
static uint8_t host_rx_dummy[HOST_FRAME_BYTES];
static uint16_t host_sequence;
static uint8_t test_mux_channel;
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

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_SPI1_Init(void);
static void MX_SPI3_Init(void);
/* USER CODE BEGIN PFP */

static void MUX1_SelectRow(uint8_t row);
static HAL_StatusTypeDef MAX11633_Init(void);
static HAL_StatusTypeDef MAX11633_ReadChannel(uint8_t channel,
                                              uint16_t *sample);
static HAL_StatusTypeDef ADC_ReadMuxChannel(uint8_t mux_channel,
                                            uint16_t *sample);
static HAL_StatusTypeDef HOST_SendLiveSample(uint8_t mux_channel,
                                             uint16_t sample);
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
  MX_SPI3_Init();
  /* USER CODE BEGIN 2 */

  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  fsr_scan_status = MAX11633_Init();

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    if (fsr_scan_status == HAL_OK)
    {
      fsr_scan_status = ADC_ReadMuxChannel(test_mux_channel,
                                           &adc_test_sample);
      if (fsr_scan_status == HAL_OK)
      {
        ++fsr_completed_scans;
        fsr_scan_status = HOST_SendLiveSample(test_mux_channel,
                                              adc_test_sample);
        if (fsr_scan_status == HAL_OK)
        {
          ++fsr_completed_frames;
          fsr_stage = FSR_STAGE_IDLE;
          test_mux_channel =
              (uint8_t)((test_mux_channel + 1U) % MUX_CHANNELS);
          HAL_Delay(MUX_STEP_PERIOD_MS);
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
      (void)HAL_SPI_Abort(&hspi1);
      (void)HAL_SPI_Abort(&hspi3);
      /*
       * A partial slave transaction can leave SPI3 misaligned even after an
       * abort. Reinitialise it so the following frame starts from byte zero.
       */
      (void)HAL_SPI_DeInit(&hspi3);
      MX_SPI3_Init();
      HAL_Delay(10U);
      fsr_scan_status = MAX11633_Init();
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

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, MUX_S0_Pin|MUX_S1_Pin|MUX_S2_Pin|MUX_S3_Pin,
                    GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);

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

  /*Configure GPIO pins : ADC_EOC1_Pin HOST_SYNC_Pin */
  GPIO_InitStruct.Pin = ADC_EOC1_Pin|HOST_SYNC_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

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

static HAL_StatusTypeDef MAX11633_ReadChannel(uint8_t channel,
                                              uint16_t *sample)
{
  uint8_t conversion_command;
  uint8_t rx[2] = {0};
  HAL_StatusTypeDef status;

  if ((sample == NULL) || (channel >= 16U))
  {
    return HAL_ERROR;
  }

  /*
   * Conversion register:
   * bit 7 = 1, CHSEL[3:0] = channel, SCAN[1:0] = 11 (one conversion).
   */
  conversion_command =
      (uint8_t)(MAX11633_SINGLE_BASE | ((channel & 0x0FU) << 3U));
  fsr_stage = FSR_STAGE_ADC_COMMAND;
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_RESET);
  status = HAL_SPI_Transmit(&hspi1, &conversion_command, 1U,
                            MAX11633_EOC_TIMEOUT);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }

  /*
   * A single-channel conversion completes in only a few microseconds. Its EOC
   * low interval can finish before the blocking HAL transmit returns and the
   * GPIO polling loop starts. Wait a conservative 1 ms instead; this affects
   * test speed only and does not alter the raw 12-bit result.
   */
  fsr_stage = FSR_STAGE_ADC_EOC_WAIT;
  HAL_Delay(1U);

  fsr_stage = FSR_STAGE_ADC_READ;
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_RESET);
  status = HAL_SPI_Receive(&hspi1, rx, sizeof(rx), MAX11633_EOC_TIMEOUT);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin, GPIO_PIN_SET);
  if (status != HAL_OK)
  {
    return status;
  }

  /* MAX11633 returns one 12-bit result with four leading zero bits. */
  *sample = (uint16_t)(((uint16_t)rx[0] << 8U) | rx[1]);
  *sample &= 0x0FFFU;
  return HAL_OK;
}

static HAL_StatusTypeDef ADC_ReadMuxChannel(uint8_t mux_channel,
                                            uint16_t *sample)
{
  HAL_StatusTypeDef status;

  if ((sample == NULL) || (mux_channel >= MUX_CHANNELS))
  {
    return HAL_ERROR;
  }

  fsr_active_row = mux_channel;
  MUX1_SelectRow(mux_channel);
  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_RESET);
  fsr_stage = FSR_STAGE_MUX_SETTLE;
  HAL_Delay(2U);

  status = MAX11633_ReadChannel(TEST_ADC_CHANNEL, sample);
  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
  return status;
}

static HAL_StatusTypeDef HOST_SendLiveSample(uint8_t mux_channel,
                                             uint16_t sample)
{
  uint32_t offset = 0U;
  HAL_StatusTypeDef status;
  uint8_t checksum = 0U;

  host_tx_frame[offset++] = HOST_FRAME_MAGIC;
  host_tx_frame[offset++] = (uint8_t)(host_sequence & 0xFFU);
  host_tx_frame[offset++] = (uint8_t)(host_sequence >> 8U);
  ++host_sequence;
  host_tx_frame[offset++] = mux_channel;
  host_tx_frame[offset++] = TEST_ADC_CHANNEL;
  host_tx_frame[offset++] = (uint8_t)(sample & 0xFFU);
  host_tx_frame[offset++] = (uint8_t)((sample >> 8U) & 0x0FU);
  for (uint32_t index = 0U; index < offset; ++index)
  {
    checksum ^= host_tx_frame[index];
  }
  host_tx_frame[offset++] = checksum;

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
