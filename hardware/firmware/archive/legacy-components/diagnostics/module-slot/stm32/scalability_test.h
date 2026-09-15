#ifndef SCALABLITY_TEST_H
#define SCALABLITY_TEST_H

#include <stdint.h>

/*
 * All STM32 modules run the same combined acquisition image. Module selection
 * is a Host-side CS/IRQ choice, not a different ADC/FSR algorithm. This small
 * contract lets a future STM32 test build carry an optional compile-time ID
 * without changing the stable ESK1 payload.
 */
#ifndef SCALABILITY_MODULE_ID
#define SCALABILITY_MODULE_ID 0U
#endif

#define SCALABILITY_MODULE_COUNT 4U

typedef struct
{
  uint8_t module_id;
  uint8_t host_spi_slave;
  uint8_t host_irq_output;
} ScalabilityTestConfig;

const ScalabilityTestConfig *ScalabilityTest_GetConfig(void);
uint8_t ScalabilityTest_IsValidModule(uint8_t module_id);

#endif
