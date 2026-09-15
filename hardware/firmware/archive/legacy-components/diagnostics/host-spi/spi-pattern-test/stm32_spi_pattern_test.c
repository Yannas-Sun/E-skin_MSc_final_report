/*
 * STM32 SPI3 slave pattern test.
 *
 * Keep this file separate from the production main.c. It is intended to be
 * copied into a temporary CubeMX test main file after MX_SPI3_Init() has run.
 * The STM32 cannot initiate an SPI transfer as a slave: the Teensy must
 * provide the clock and NSS pulse.
 */
#include "main.h"

#define SPI_TEST_BYTE 0x55U /* 01010101 */

void SPI_PatternTest_Once(void)
{
    uint8_t tx = SPI_TEST_BYTE;
    uint8_t rx = 0U;

    /* Teensy selects the slave and clocks one byte. */
    (void)HAL_SPI_TransmitReceive(&hspi3, &tx, &rx, 1U, 100U);
}

/* Example temporary main-loop body:
 *
 * while (1) {
 *     SPI_PatternTest_Once();
 *     HAL_Delay(10);
 * }
 */
