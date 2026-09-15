#ifndef DATA_SCALABILITY_PROTOCOL_H
#define DATA_SCALABILITY_PROTOCOL_H

#include <stdint.h>

#define DATA_SCALABILITY_FRAME_BYTES 1044U /* maximum frame buffer capacity */

#define DATA_SCALABILITY_MODE_FULL 0U
#define DATA_SCALABILITY_MODE_DELTA 1U
#define DATA_SCALABILITY_MODE_SPATIAL 2U

/* The command shares the first full-duplex bytes with the frame header. */
#define DATA_SCALABILITY_COMMAND_BYTES 12U
#define DATA_SCALABILITY_COMMAND_VERSION 3U
#define DATA_SCALABILITY_COMMAND_MODE_MASK 0x03U
#define DATA_SCALABILITY_COMMAND_FLAG_DELTA_RESYNC 0x40U
#define DATA_SCALABILITY_COMMAND_FLAG_SPATIAL_RESYNC 0x80U

void DataScalability_Init(void);
void DataScalability_SetMode(uint8_t mode);
uint8_t DataScalability_GetMode(void);
void DataScalability_ApplyCommand(const uint8_t *command, uint16_t length);

/*
 * Encode one protocol frame into a maximum-capacity host buffer.
 * The returned value is the exact on-wire frame length. The unused tail of
 * target is cleared only as RAM workspace; Host SPI must transmit the
 * returned length and must not send the unused tail.
 */
uint16_t DataScalability_Encode(uint8_t *target,
                                const uint16_t *fsr1,
                                const uint16_t *fsr2,
                                uint32_t now_ms,
                                uint8_t base_flags);

uint16_t DataScalability_GetScanRateHz(void);

#endif
