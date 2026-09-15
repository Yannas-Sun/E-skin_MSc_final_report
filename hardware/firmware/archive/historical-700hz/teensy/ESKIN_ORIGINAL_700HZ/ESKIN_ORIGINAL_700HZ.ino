/*
 * Original Teensy-direct E-SKIN acquisition path, scheduled at nominal 700 Hz.
 *
 * The sensor drivers and pin map are intentionally taken directly from the
 * preserved original firmware. This sketch only reproduces the active-stream
 * loop that the legacy software generated before compiling the Teensy image.
 */
#include "../../../previous/src/Eskin/fsr.hpp"
#include "../../../previous/src/Eskin/lis3dh.h"
#include "../../../previous/src/Eskin/lis3dh.cpp"

#define ACC_SAMPLE_RATE 700
#define FSR_SAMPLE_RATE 700

static constexpr uint32_t STREAM_INTERVAL_US = 1000000UL / FSR_SAMPLE_RATE;
static constexpr uint8_t FSR_SIZE = 16U;

FSR fsr;
LIS3DH lis3dh[16];
uint8_t LIS3DH::last_index = 0;

int16_t acc_data[3 * 16];
uint16_t fsr_data[2 * 16 * 16];
uint32_t ts_acc = 0;
uint32_t ts_fsr = 0;

void setup()
{
    Serial.begin(115200);
    fsr.begin();
    delay(1000);

    SPI1.begin();
    for(int i = 0; i < 16; ++i)
    {
        lis3dh[i].begin(SPI1, i);
        lis3dh[i].setFullScaleRange(LIS3DH_RANGE_2G);
        lis3dh[i].setOutputDataRate(LIS3DH_DATARATE_5KHZ);
        lis3dh[i].setHighSolution(true);
        delay(1);
    }
}

void loop()
{
    static uint32_t last_stream_us = 0;
    const uint32_t now = micros();
    if((uint32_t)(now - last_stream_us) < STREAM_INTERVAL_US)
        return;
    last_stream_us = now;

    ts_acc = micros();
    for(int i = 0; i < 16; ++i)
        lis3dh[i].getAccelerationRaw((uint8_t *)&acc_data[i * 3]);

    ts_fsr = micros();
    fsr.scan_2array(fsr_data, FSR_SIZE);

    /* Preserve the legacy hardware correction used by the old generator. */
    for(int selected_row = 0; selected_row < 16; ++selected_row)
    {
        const int layer2_row8_index = selected_row * 32 + 16 + 7;
        fsr_data[layer2_row8_index] /= 7U;
    }

    Serial.write((const uint8_t *)"ESKN", 4);
    Serial.write((uint8_t *)&ts_acc, 4);
    Serial.write((uint8_t *)&ts_fsr, 4);
    Serial.write((uint8_t *)&acc_data, sizeof(acc_data));
    Serial.write((uint8_t *)&fsr_data, sizeof(fsr_data));
}
