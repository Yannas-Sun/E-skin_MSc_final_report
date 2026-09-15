/* Included after real acquisition and protocol C; only HAL/hardware is simulated. */
#include <assert.h>
#include <stdio.h>
MockCoreDebug mock_core_debug;
MockDWT mock_dwt;
uint32_t SystemCoreClock = 1000000;
static DMA_HandleTypeDef receive_dma;
SPI_HandleTypeDef hspi1 = { (void*)1, NULL };
SPI_HandleTypeDef hspi3 = { SPI3, &receive_dma };
static uint32_t tick;
static uint8_t mock_command[16];
static uint8_t* dma_owned;
static uint8_t dma_snapshot[1044];
static uint16_t dma_lengths[32];
static unsigned dma_calls, abort_calls, reinit_calls, wfi_calls;
static uint16_t current_dma_length;
static GPIO_PinState nss = GPIO_PIN_SET, irq;
enum Scenario { FINISH, PAUSE_LOW, NEVER_START, PARTIAL_RELEASE, DMA_ERROR, RACE_TO_LOW, MISSING_CALLBACK };
static enum Scenario scenario;
static unsigned scenario_wakes;

void mock_nop(void) { mock_dwt.CYCCNT += 100; }
uint32_t HAL_GetTick(void) { return tick++; }
void HAL_Delay(uint32_t ms) { tick += ms; }
void HAL_GPIO_WritePin(void* port, uint16_t pin, GPIO_PinState level) {
  if (port == GPIOB && pin == HOST_IRQ_Pin) irq = level;
}
GPIO_PinState HAL_GPIO_ReadPin(void* port, uint16_t pin) {
  return (port == GPIOA && pin == GPIO_PIN_15) ? nss : GPIO_PIN_RESET;
}
void HAL_GPIO_Init(void* port, GPIO_InitTypeDef* config) { (void)port; (void)config; }
HAL_StatusTypeDef HAL_SPI_Transmit(SPI_HandleTypeDef* spi, uint8_t* data, uint16_t n, uint32_t timeout) {
  (void)spi; (void)data; (void)n; (void)timeout; return HAL_OK;
}
HAL_StatusTypeDef HAL_SPI_Receive(SPI_HandleTypeDef* spi, uint8_t* data, uint16_t n, uint32_t timeout) {
  (void)spi; (void)timeout;
  for (unsigned i = 0; i < n; i += 2) { data[i] = 0; data[i + 1] = 100; }
  return HAL_OK;
}
HAL_StatusTypeDef HAL_SPI_Abort(SPI_HandleTypeDef* spi) {
  (void)spi; ++abort_calls; dma_owned = NULL; return HAL_OK;
}
void Combined_ReinitializeHostSPI(void) { ++reinit_calls; }
HAL_StatusTypeDef HAL_SPI_TransmitReceive_DMA(SPI_HandleTypeDef* spi, uint8_t* tx, uint8_t* rx, uint16_t length) {
  assert(spi == &hspi3 && length >= 84 && length <= 1044);
  assert(length == ((uint16_t)tx[6] | (uint16_t)tx[7] << 8));
  assert(dma_owned == NULL && irq == GPIO_PIN_RESET);
  current_dma_length = length;
  dma_lengths[dma_calls++] = length;
  dma_owned = tx; memcpy(dma_snapshot, tx, length);
  memcpy(rx, mock_command, 16);
  receive_dma.remaining = length;
  scenario_wakes = 0;
  if (scenario == PARTIAL_RELEASE || scenario == PAUSE_LOW || scenario == RACE_TO_LOW) receive_dma.remaining -= 16;
  if (scenario == MISSING_CALLBACK) receive_dma.remaining = 0;
  nss = scenario == PAUSE_LOW ? GPIO_PIN_RESET : GPIO_PIN_SET;
  return HAL_OK;
}
uint32_t mock_dma_counter(DMA_HandleTypeDef* dma) {
  assert(dma == &receive_dma);
  if (scenario == RACE_TO_LOW) nss = GPIO_PIN_RESET;
  return dma->remaining;
}
void mock_wfi(void) {
  ++wfi_calls; ++scenario_wakes; ++tick;
  if (dma_owned) assert(memcmp(dma_owned, dma_snapshot, current_dma_length) == 0);
  if (scenario == NEVER_START || scenario == MISSING_CALLBACK) return;
  if ((scenario == PAUSE_LOW || scenario == RACE_TO_LOW) && scenario_wakes < 4) return;
  nss = GPIO_PIN_SET; receive_dma.remaining = 0;
  if (scenario == DMA_ERROR) HAL_SPI_ErrorCallback(&hspi3);
  else HAL_SPI_TxRxCpltCallback(&hspi3);
  dma_owned = NULL;
}
static void set_command(uint8_t mode_value, uint8_t flags) {
  memset(mock_command, 0, sizeof(mock_command));
  memcpy(mock_command, "DSCM", 4); mock_command[4] = 2;
  mock_command[5] = mode_value; mock_command[6] = 8; mock_command[12] = flags;
}
static void check_next_buffer(uint16_t expected, const char* magic) {
  assert(host_frame_length[host_send_index] == expected);
  assert(memcmp(host_tx[host_send_index], magic, 4) == 0);
  assert(host_send_index != host_fill_index);
  assert(irq == GPIO_PIN_RESET && host_dma_active == 0);
}
static void run_scenario(enum Scenario value, HAL_StatusTypeDef expected) {
  scenario = value; nss = GPIO_PIN_SET; irq = GPIO_PIN_RESET;
  unsigned abort_before = abort_calls;
  unsigned error_before = host_dma_error_count;
  unsigned timeout_before = host_dma_timeout_count;
  assert(start_frame_dma(host_send_index) == HAL_OK);
  unsigned wakes_before = wfi_calls;
  assert(wait_frame_dma(host_frame_length[host_send_index]) == expected);
  assert(irq == GPIO_PIN_RESET && host_dma_active == 0);
  if (expected == HAL_OK) assert(abort_calls == abort_before + 1);
  if (expected == HAL_ERROR) assert(host_dma_error_count == error_before + 1);
  if (expected == HAL_TIMEOUT) assert(host_dma_timeout_count == timeout_before + 1);
  if (value == PARTIAL_RELEASE) assert(wfi_calls == wakes_before);
  if (value == PAUSE_LOW || value == RACE_TO_LOW) assert(wfi_calls >= wakes_before + 4);
}
int main(void) {
  CombinedAcquisition_Init();
  set_command(1, 0); scenario = FINISH;
  CombinedAcquisition_RunOnce();
  assert(dma_lengths[0] == 1044); check_next_buffer(1044, "ESKF");
  assert(host_tx[host_send_index][5] & 0x20);
  CombinedAcquisition_RunOnce();
  assert(dma_lengths[1] == 1044); check_next_buffer(84, "ESKD");
  set_command(1, 1);
  CombinedAcquisition_RunOnce();
  assert(dma_lengths[2] == 84); check_next_buffer(1044, "ESKF");
  set_command(1, 0);
  CombinedAcquisition_RunOnce();
  assert(dma_lengths[3] == 1044); check_next_buffer(84, "ESKD");
  set_command(0, 0);
  CombinedAcquisition_RunOnce();
  assert(dma_lengths[4] == 84); check_next_buffer(1044, "ESKF");
  assert(!(host_tx[host_send_index][5] & 0x20));
  run_scenario(PAUSE_LOW, HAL_OK);
  run_scenario(RACE_TO_LOW, HAL_OK);
  run_scenario(PARTIAL_RELEASE, HAL_ERROR);
  run_scenario(DMA_ERROR, HAL_ERROR);
  run_scenario(NEVER_START, HAL_TIMEOUT);
  run_scenario(MISSING_CALLBACK, HAL_TIMEOUT);
  host_frame_length[host_send_index] = 0;
  assert(start_frame_dma(host_send_index) == HAL_ERROR);
  host_frame_length[host_send_index] = 1045;
  assert(start_frame_dma(host_send_index) == HAL_ERROR);
  fprintf(stderr, "DMA: 5 real pipeline rounds; mode/resync length, immutable active buffer, 6 completion/failure scenarios, bounds passed\n");
  return 0;
}
