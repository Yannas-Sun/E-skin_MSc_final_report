#include "combined_acquisition.h"
#include "main.h"

#include <string.h>

extern SPI_HandleTypeDef hspi2;

#define ACC_COUNT 9U
#define ACC_WHO_REG 0x0FU
#define ACC_WHO_EXPECTED 0x33U
#define ACC_STATUS_REG 0x27U
#define ACC_CTRL1_REG 0x20U
#define ACC_CTRL4_REG 0x23U
#define ACC_READ 0x80U
#define ACC_INCREMENT 0x40U
#define ACC_SPI_TIMEOUT_MS 2U
#define ACC_INIT_ATTEMPTS 5U
#define ACC_INIT_RETRY_MS 5U
#define ACC_SPI_PRESCALER 16U
#define ACC_BENCH_SIGNATURE 0x42434341UL /* "ACCB" in little endian. */
#define ACC_BENCH_VERSION 1U

#ifndef ACC_BENCH_MODE
#error "ACC_BENCH_MODE must be supplied by the isolated benchmark profile"
#endif
#ifndef ACC_BENCH_CTRL1
#error "ACC_BENCH_CTRL1 must be supplied by the isolated benchmark profile"
#endif
#ifndef ACC_BENCH_CTRL4
#error "ACC_BENCH_CTRL4 must be supplied by the isolated benchmark profile"
#endif

typedef struct
{
  uint32_t signature;
  uint32_t version;
  uint32_t word_count;
  uint32_t generation;
  uint32_t mode;
  uint32_t ctrl1_requested;
  uint32_t ctrl4_requested;
  uint32_t system_core_clock_hz;
  uint32_t spi_clock_hz;
  uint32_t window_cycles;
  uint32_t complete_scan_count;
  uint32_t slot_transaction_count;
  uint32_t spi_error_count;
  uint32_t online_mask;
  uint32_t init_error_mask;
  uint32_t online_count;
  uint32_t who[ACC_COUNT];
  uint32_t ctrl1_readback[ACC_COUNT];
  uint32_t ctrl4_readback[ACC_COUNT];
  uint32_t data_ready_count[ACC_COUNT];
  uint32_t duplicate_count[ACC_COUNT];
  uint32_t last_status[ACC_COUNT];
  int32_t last_x[ACC_COUNT];
  int32_t last_y[ACC_COUNT];
  int32_t last_z[ACC_COUNT];
} AccBenchmarkSnapshot;

/* Deliberately global and retained so the PC can locate it in the ELF and
 * read one-second snapshots through SWD without involving Host SPI or USB. */
volatile AccBenchmarkSnapshot g_acc_benchmark_snapshot
    __attribute__((used, aligned(4)));

static uint8_t acc_who[ACC_COUNT];
static uint8_t acc_ctrl1[ACC_COUNT];
static uint8_t acc_ctrl4[ACC_COUNT];
static uint16_t acc_online_mask;
static uint16_t acc_init_error_mask;
static uint32_t snapshot_generation;

static void acc_deselect(void)
{
  HAL_GPIO_WritePin(ACC_ENABLE_GPIO_Port, ACC_ENABLE_Pin, GPIO_PIN_SET);
}

static void acc_select(uint8_t index)
{
  acc_deselect();
  HAL_GPIO_WritePin(ACC_ADDR0_GPIO_Port, ACC_ADDR0_Pin,
                    (index & 0x01U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR1_GPIO_Port, ACC_ADDR1_Pin,
                    (index & 0x02U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR2_GPIO_Port, ACC_ADDR2_Pin,
                    (index & 0x04U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(ACC_ADDR3_GPIO_Port, ACC_ADDR3_Pin,
                    (index & 0x08U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  for (volatile uint32_t delay = 0U; delay < 64U; ++delay) { __NOP(); }
  HAL_GPIO_WritePin(ACC_ENABLE_GPIO_Port, ACC_ENABLE_Pin, GPIO_PIN_RESET);
  for (volatile uint32_t delay = 0U; delay < 64U; ++delay) { __NOP(); }
}

static HAL_StatusTypeDef acc_transfer(uint8_t index, uint8_t *tx,
                                      uint8_t *rx, uint16_t size)
{
  acc_select(index);
  const HAL_StatusTypeDef status = HAL_SPI_TransmitReceive(
      &hspi2, tx, rx, size, ACC_SPI_TIMEOUT_MS);
  acc_deselect();
  return status;
}

static HAL_StatusTypeDef acc_read_reg(uint8_t index, uint8_t reg,
                                      uint8_t *value)
{
  uint8_t tx[2] = {(uint8_t)(ACC_READ | (reg & 0x3FU)), 0U};
  uint8_t rx[2] = {0U};
  const HAL_StatusTypeDef status = acc_transfer(index, tx, rx, sizeof(tx));
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

static uint8_t acc_init_one(uint8_t index)
{
  for (uint8_t attempt = 0U; attempt < ACC_INIT_ATTEMPTS; ++attempt)
  {
    uint8_t who = 0U;
    uint8_t ctrl1 = 0U;
    uint8_t ctrl4 = 0U;
    HAL_Delay(ACC_INIT_RETRY_MS);
    if ((acc_read_reg(index, ACC_WHO_REG, &who) == HAL_OK) &&
        (who == ACC_WHO_EXPECTED) &&
        /* Set HR before ODR/LPen. This avoids the forbidden LPen=1,HR=1
         * intermediate state when entering the 5.376 kHz low-power mode. */
        (acc_write_reg(index, ACC_CTRL4_REG, ACC_BENCH_CTRL4) == HAL_OK) &&
        (acc_write_reg(index, ACC_CTRL1_REG, ACC_BENCH_CTRL1) == HAL_OK))
    {
      HAL_Delay(2U);
      if ((acc_read_reg(index, ACC_CTRL1_REG, &ctrl1) == HAL_OK) &&
          (acc_read_reg(index, ACC_CTRL4_REG, &ctrl4) == HAL_OK) &&
          (ctrl1 == ACC_BENCH_CTRL1) && (ctrl4 == ACC_BENCH_CTRL4))
      {
        acc_who[index] = who;
        acc_ctrl1[index] = ctrl1;
        acc_ctrl4[index] = ctrl4;
        return 1U;
      }
    }
    acc_who[index] = who;
    acc_ctrl1[index] = ctrl1;
    acc_ctrl4[index] = ctrl4;
  }
  return 0U;
}

static int32_t signed_output(uint8_t low, uint8_t high)
{
  const int16_t raw = (int16_t)(((uint16_t)high << 8U) | low);
#if ACC_BENCH_MODE == 1U
  return (int32_t)(raw >> 4U); /* 12-bit high-resolution result. */
#else
  return (int32_t)(raw >> 8U); /* 8-bit low-power result. */
#endif
}

void CombinedAcquisition_Init(void)
{
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0U;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

  HAL_GPIO_WritePin(GPIOA, MUX_EN1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, ADC_CS1_Pin | ADC_CS2_Pin | MUX_EN2_Pin,
                    GPIO_PIN_SET);
  HAL_GPIO_WritePin(GPIOB, HOST_IRQ_Pin, GPIO_PIN_RESET);
  acc_deselect();
  HAL_Delay(1000U);

  memset(acc_who, 0, sizeof(acc_who));
  memset(acc_ctrl1, 0, sizeof(acc_ctrl1));
  memset(acc_ctrl4, 0, sizeof(acc_ctrl4));
  acc_online_mask = 0U;
  acc_init_error_mask = 0U;
  for (uint8_t index = 0U; index < ACC_COUNT; ++index)
  {
    if (acc_init_one(index) != 0U)
    {
      acc_online_mask |= (uint16_t)(1U << index);
    }
    else
    {
      acc_init_error_mask |= (uint16_t)(1U << index);
    }
  }
  memset((void *)&g_acc_benchmark_snapshot, 0,
         sizeof(g_acc_benchmark_snapshot));
  acc_deselect();
}

void CombinedAcquisition_RunOnce(void)
{
  uint32_t ready_count[ACC_COUNT] = {0U};
  uint32_t duplicate_count[ACC_COUNT] = {0U};
  uint32_t last_status[ACC_COUNT] = {0U};
  int32_t last_x[ACC_COUNT] = {0};
  int32_t last_y[ACC_COUNT] = {0};
  int32_t last_z[ACC_COUNT] = {0};
  uint32_t complete_scans = 0U;
  uint32_t slot_transactions = 0U;
  uint32_t spi_errors = 0U;
  const uint32_t started = DWT->CYCCNT;

  do
  {
    for (uint8_t index = 0U; index < ACC_COUNT; ++index)
    {
      /* MS=1 auto-increments the continuous 0x27..0x2D register range, so
       * one 8-byte transaction captures ZYXDA before reading the matching
       * XYZ values. Reading the three high bytes then clears the DA flags. */
      uint8_t tx[8] = {
          (uint8_t)(ACC_READ | ACC_INCREMENT | ACC_STATUS_REG),
          0U, 0U, 0U, 0U, 0U, 0U, 0U};
      uint8_t rx[8] = {0U};
      if (acc_transfer(index, tx, rx, sizeof(tx)) != HAL_OK)
      {
        ++spi_errors;
        continue;
      }
      ++slot_transactions;
      last_status[index] = rx[1];
      if ((acc_online_mask & (uint16_t)(1U << index)) == 0U) { continue; }

      if ((rx[1] & 0x08U) != 0U) { ++ready_count[index]; }
      else { ++duplicate_count[index]; }
      last_x[index] = signed_output(rx[2], rx[3]);
      last_y[index] = signed_output(rx[4], rx[5]);
      last_z[index] = signed_output(rx[6], rx[7]);
    }
    ++complete_scans;
  }
  while ((uint32_t)(DWT->CYCCNT - started) < SystemCoreClock);

  const uint32_t elapsed_cycles = (uint32_t)(DWT->CYCCNT - started);
  const uint32_t publishing_generation = snapshot_generation + 1U;
  g_acc_benchmark_snapshot.generation = publishing_generation;
  __DMB();
  g_acc_benchmark_snapshot.signature = ACC_BENCH_SIGNATURE;
  g_acc_benchmark_snapshot.version = ACC_BENCH_VERSION;
  g_acc_benchmark_snapshot.word_count =
      (uint32_t)(sizeof(AccBenchmarkSnapshot) / sizeof(uint32_t));
  g_acc_benchmark_snapshot.mode = ACC_BENCH_MODE;
  g_acc_benchmark_snapshot.ctrl1_requested = ACC_BENCH_CTRL1;
  g_acc_benchmark_snapshot.ctrl4_requested = ACC_BENCH_CTRL4;
  g_acc_benchmark_snapshot.system_core_clock_hz = SystemCoreClock;
  g_acc_benchmark_snapshot.spi_clock_hz =
      HAL_RCC_GetPCLK1Freq() / ACC_SPI_PRESCALER;
  g_acc_benchmark_snapshot.window_cycles = elapsed_cycles;
  g_acc_benchmark_snapshot.complete_scan_count = complete_scans;
  g_acc_benchmark_snapshot.slot_transaction_count = slot_transactions;
  g_acc_benchmark_snapshot.spi_error_count = spi_errors;
  g_acc_benchmark_snapshot.online_mask = acc_online_mask;
  g_acc_benchmark_snapshot.init_error_mask = acc_init_error_mask;
  g_acc_benchmark_snapshot.online_count =
      (uint32_t)__builtin_popcount((unsigned int)acc_online_mask);
  for (uint8_t index = 0U; index < ACC_COUNT; ++index)
  {
    g_acc_benchmark_snapshot.who[index] = acc_who[index];
    g_acc_benchmark_snapshot.ctrl1_readback[index] = acc_ctrl1[index];
    g_acc_benchmark_snapshot.ctrl4_readback[index] = acc_ctrl4[index];
    g_acc_benchmark_snapshot.data_ready_count[index] = ready_count[index];
    g_acc_benchmark_snapshot.duplicate_count[index] = duplicate_count[index];
    g_acc_benchmark_snapshot.last_status[index] = last_status[index];
    g_acc_benchmark_snapshot.last_x[index] = last_x[index];
    g_acc_benchmark_snapshot.last_y[index] = last_y[index];
    g_acc_benchmark_snapshot.last_z[index] = last_z[index];
  }
  __DMB();
  snapshot_generation = publishing_generation + 1U;
  g_acc_benchmark_snapshot.generation = snapshot_generation;
  __DMB();
}
