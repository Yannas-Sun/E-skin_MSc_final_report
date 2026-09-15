#ifndef DATA_SCALABILITY_PROTOCOL_H
#define DATA_SCALABILITY_PROTOCOL_H

#include <stdint.h>

#define DATA_SCALABILITY_FRAME_BYTES 1044U

#define DATA_SCALABILITY_MODE_FULL 0U
#define DATA_SCALABILITY_MODE_DELTA 1U

/* DSCM v2 MOSI command: mode at 5, Delta threshold at 6..7, reserved at
 * 8..9, scan rate at 10..11, flags at 12, and reserved at 13..15. */
#define DATA_SCALABILITY_COMMAND_BYTES 16U
#define DATA_SCALABILITY_COMMAND_FLAG_DELTA_RESYNC 0x01U

void DataScalability_Init(void);
void DataScalability_SetMode(uint8_t mode);
uint8_t DataScalability_GetMode(void);
void DataScalability_ApplyCommand(const uint8_t *command, uint16_t length);

/*
 * Encode one protocol frame into a 1044-byte-capacity host buffer.
 * The returned value is the complete frame length, including its CRC, and
 * determines the single SPI3 DMA transfer length. The unused tail is cleared
 * for deterministic buffer contents but is not transmitted.
 */
uint16_t DataScalability_Encode(uint8_t *target,
                                const uint16_t *fsr1,
                                const uint16_t *fsr2,
                                uint32_t now_ms,
                                uint8_t base_flags);

uint16_t DataScalability_GetScanRateHz(void);

#endif
