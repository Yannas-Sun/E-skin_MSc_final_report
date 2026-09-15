#include "main.h"
#include "combined_acquisition.h"

SPI_HandleTypeDef hspi1;
SPI_HandleTypeDef hspi3;
DMA_HandleTypeDef hdma_spi3_rx;
DMA_HandleTypeDef hdma_spi3_tx;

void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_SPI1_Init(void);
static void MX_SPI3_Init(void);
static void MX_DMA_Init(void);

int main(void)
{
  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_SPI1_Init();
  MX_SPI3_Init();
  CombinedAcquisition_Init();

  while (1)
  {
    CombinedAcquisition_RunOnce();
  }
}

void SystemClock_Config(void)
{
  RCC_OscInitTypeDef osc = {0};
  RCC_ClkInitTypeDef clock = {0};

#ifdef SCLK33_SYSCLK_HIGH
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1_BOOST);
#else
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);
#endif

  osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  osc.HSIState = RCC_HSI_ON;
  osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  osc.PLL.PLLState = RCC_PLL_ON;
  osc.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  osc.PLL.PLLM = RCC_PLLM_DIV4;
#ifdef SCLK33_SYSCLK_HIGH
  osc.PLL.PLLN = SCLK33_PLLN;
#else
  osc.PLL.PLLN = 40U;
#endif
  osc.PLL.PLLP = RCC_PLLP_DIV2;
  osc.PLL.PLLQ = RCC_PLLQ_DIV2;
  osc.PLL.PLLR = RCC_PLLR_DIV2;
  if (HAL_RCC_OscConfig(&osc) != HAL_OK) { Error_Handler(); }

  clock.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                    RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  clock.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  clock.AHBCLKDivider = RCC_SYSCLK_DIV1;
  clock.APB1CLKDivider = RCC_HCLK_DIV1;
  clock.APB2CLKDivider = RCC_HCLK_DIV1;
#ifdef SCLK33_SYSCLK_HIGH
  if (HAL_RCC_ClockConfig(&clock, FLASH_LATENCY_4) != HAL_OK)
#else
  if (HAL_RCC_ClockConfig(&clock, FLASH_LATENCY_2) != HAL_OK)
#endif
  {
    Error_Handler();
  }
}

static void MX_SPI1_Init(void)
{
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
#ifdef SCLK33_SPI_BAUDRATE_PRESCALER
  hspi1.Init.BaudRatePrescaler = SCLK33_SPI_BAUDRATE_PRESCALER;
#else
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_8;
#endif
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 7U;
  hspi1.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_ENABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK) { Error_Handler(); }
}

static void MX_SPI3_Init(void)
{
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
  hspi3.Init.CRCPolynomial = 7U;
  hspi3.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi3.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  if (HAL_SPI_Init(&hspi3) != HAL_OK) { Error_Handler(); }
}

void Combined_ReinitializeHostSPI(void)
{
  (void)HAL_SPI_DeInit(&hspi3);
  __HAL_RCC_SPI3_FORCE_RESET();
  __DSB();
  __HAL_RCC_SPI3_RELEASE_RESET();
  __DSB();
  MX_SPI3_Init();
}

static void MX_DMA_Init(void)
{
  __HAL_RCC_DMAMUX1_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();
  HAL_NVIC_SetPriority(DMA1_Channel1_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel1_IRQn);
  HAL_NVIC_SetPriority(DMA1_Channel2_IRQn, 1, 1);
  HAL_NVIC_EnableIRQ(DMA1_Channel2_IRQn);
}

static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef gpio = {0};
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  HAL_GPIO_WritePin(GPIOA, MUX_S0_Pin | MUX_S1_Pin | MUX_S2_Pin |
                           MUX_S3_Pin | MUX_EN1_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin | ADC_CS2_Pin | MUX_EN2_Pin,
                    GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);

  gpio.Pin = MUX_S0_Pin | MUX_S1_Pin | MUX_S2_Pin | MUX_S3_Pin | MUX_EN1_Pin;
  gpio.Mode = GPIO_MODE_OUTPUT_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &gpio);

  gpio.Pin = ADC_CS1_Pin | ADC_CS2_Pin | MUX_EN2_Pin | HOST_IRQ_Pin;
  HAL_GPIO_Init(GPIOB, &gpio);

  gpio.Pin = ADC_EOC1_Pin | ADC_EOC2_Pin | HOST_SYNC_Pin;
  gpio.Mode = GPIO_MODE_INPUT;
  HAL_GPIO_Init(GPIOB, &gpio);
}

void Error_Handler(void)
{
  __disable_irq();
  while (1) { }
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
  (void)file;
  (void)line;
}
#endif
