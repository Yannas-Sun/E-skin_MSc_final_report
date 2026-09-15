#pragma once
#include <stdint.h>
#include <stddef.h>
typedef enum { HAL_OK, HAL_ERROR, HAL_BUSY, HAL_TIMEOUT } HAL_StatusTypeDef;
typedef enum { GPIO_PIN_RESET, GPIO_PIN_SET } GPIO_PinState;
typedef struct { uint32_t remaining; } DMA_HandleTypeDef;
typedef struct { void *Instance; DMA_HandleTypeDef *hdmarx; } SPI_HandleTypeDef;
typedef struct { uint32_t Pin, Mode, Pull, Speed; } GPIO_InitTypeDef;
typedef struct { volatile uint32_t DEMCR; } MockCoreDebug;
typedef struct { volatile uint32_t CYCCNT, CTRL; } MockDWT;
extern MockCoreDebug mock_core_debug;
extern MockDWT mock_dwt;
#define CoreDebug (&mock_core_debug)
#define DWT (&mock_dwt)
#define CoreDebug_DEMCR_TRCENA_Msk 1
#define DWT_CTRL_CYCCNTENA_Msk 1
#define GPIOA ((void*)1)
#define GPIOB ((void*)2)
#define SPI3 ((void*)3)
#define GPIO_PIN_15 0x8000U
#define MUX_S0_Pin 1U
#define MUX_S1_Pin 2U
#define MUX_S2_Pin 4U
#define MUX_S3_Pin 8U
#define MUX_EN1_Pin 16U
#define MUX_EN2_Pin 4U
#define ADC_CS1_Pin 1U
#define ADC_CS2_Pin 2U
#define ADC_EOC1_Pin 1024U
#define ADC_EOC2_Pin 2048U
#define HOST_IRQ_Pin 256U
#define GPIO_MODE_OUTPUT_PP 0
#define GPIO_MODE_INPUT 1
#define GPIO_NOPULL 0
#define GPIO_SPEED_FREQ_LOW 0
extern uint32_t SystemCoreClock;
void mock_nop(void);
void mock_wfi(void);
uint32_t mock_dma_counter(DMA_HandleTypeDef*);
#define __NOP() mock_nop()
#define __WFI() mock_wfi()
#define __DMB() ((void)0)
#define __HAL_DMA_GET_COUNTER(handle) mock_dma_counter(handle)
uint32_t HAL_GetTick(void);
void HAL_Delay(uint32_t);
void HAL_GPIO_WritePin(void*, uint16_t, GPIO_PinState);
GPIO_PinState HAL_GPIO_ReadPin(void*, uint16_t);
void HAL_GPIO_Init(void*, GPIO_InitTypeDef*);
HAL_StatusTypeDef HAL_SPI_Transmit(SPI_HandleTypeDef*, uint8_t*, uint16_t, uint32_t);
HAL_StatusTypeDef HAL_SPI_Receive(SPI_HandleTypeDef*, uint8_t*, uint16_t, uint32_t);
HAL_StatusTypeDef HAL_SPI_Abort(SPI_HandleTypeDef*);
HAL_StatusTypeDef HAL_SPI_TransmitReceive_DMA(SPI_HandleTypeDef*, uint8_t*, uint8_t*, uint16_t);
void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef*);
void HAL_SPI_ErrorCallback(SPI_HandleTypeDef*);
