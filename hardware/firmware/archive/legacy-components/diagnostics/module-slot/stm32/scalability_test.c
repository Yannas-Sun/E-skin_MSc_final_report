#include "scalablity_test.h"

static const ScalabilityTestConfig config =
{
  (uint8_t)SCALABILITY_MODULE_ID,
  3U, /* SPI3 is the Host SPI slave on every module. */
  8U  /* PB8 / HOST_IRQ is the module-local ready signal. */
};

const ScalabilityTestConfig *ScalabilityTest_GetConfig(void)
{
  return &config;
}

uint8_t ScalabilityTest_IsValidModule(uint8_t module_id)
{
  return (module_id < SCALABILITY_MODULE_COUNT) ? 1U : 0U;
}
