#ifndef DATA_SCALABILITY_PROTOCOL_H
#define DATA_SCALABILITY_PROTOCOL_H

#include <stdint.h>

#define DATA_SCALABILITY_FRAME_BYTES 1188U

#define DATA_SCALABILITY_MODE_FULL 0U
#define DATA_SCALABILITY_MODE_DELTA 1U
#define DATA_SCALABILITY_MODE_SPATIAL 2U

/* MOSI command sent by the Teensy at the beginning of the next SPI read. */
#define DATA_SCALABILITY_COMMAND_BYTES 12U

void DataScalability_Init(void);
void DataScalability_SetMode(uint8_t mode);
uint8_t DataScalability_GetMode(void);
void DataScalability_ApplyCommand(const uint8_t *command, uint16_t length);

/*
 * Encode one protocol frame into a fixed 1188-byte host buffer.
 * The returned value is the logical frame length. The unused tail of target
 * is cleared so the existing fixed-length SPI3 DMA transaction remains safe.
 */
uint16_t DataScalability_Encode(uint8_t *target,
                                const uint16_t *fsr1,
                                const uint16_t *fsr2,
                                const uint8_t *acc_wire_144,
                                uint32_t now_ms,
                                uint8_t base_flags);

#endif
