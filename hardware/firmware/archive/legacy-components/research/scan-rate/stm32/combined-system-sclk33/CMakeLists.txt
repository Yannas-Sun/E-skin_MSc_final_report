cmake_minimum_required(VERSION 3.22)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Release")
endif()

set(CMAKE_PROJECT_NAME ESKIN_STM32_SCLK33_EXPERIMENT)
project(${CMAKE_PROJECT_NAME})
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")

enable_language(C ASM)
add_executable(${CMAKE_PROJECT_NAME})

set(SCLK33_PROFILE "safe2p5" CACHE STRING
    "SCLK33 experiment profile; includes FSR sweep and ACC rate benchmarks")
set_property(CACHE SCLK33_PROFILE PROPERTY STRINGS
    safe2p5 legacy10_settle100 legacy10 legacy10_refint
    refint9p375 refint8p75 refint8p125 refint8 refint7p5 refint6p25
    refint5p625 refint5 refint4p8125 refint4p75
    refint4p5 refint4 refint2p5 internal_fifo_dma
    stable_internal_eoc_mux_sweep
    acc_hr1344 acc_lp5376)

set(INTERNAL_FIFO_GAP_US "0" CACHE STRING
    "Internal-clock command-to-FIFO-read delay in microseconds")
set(INTERNAL_FIFO_MUX_SETTLE_US "0" CACHE STRING
    "Internal-clock external-MUX settling delay in microseconds")
set(STABLE_EOC_MUX_SETTLE_US "100" CACHE STRING
    "Stable internal-clock + EOC external-MUX settling delay in microseconds")
foreach(INTERNAL_DELAY_VAR IN ITEMS
        INTERNAL_FIFO_GAP_US INTERNAL_FIFO_MUX_SETTLE_US STABLE_EOC_MUX_SETTLE_US)
    if(NOT "${${INTERNAL_DELAY_VAR}}" MATCHES "^[0-9]+$")
        message(FATAL_ERROR
            "${INTERNAL_DELAY_VAR} must be a non-negative integer in us "
            "(got '${${INTERNAL_DELAY_VAR}}')")
    endif()
    if(${${INTERNAL_DELAY_VAR}} GREATER 1000)
        message(FATAL_ERROR
            "${INTERNAL_DELAY_VAR} must be <= 1000 us "
            "(got '${${INTERNAL_DELAY_VAR}}')")
    endif()
endforeach()

# The transport remains a fixed-size frame loop, while the replicated sensor
# groups may be refreshed independently. Zero preserves the historical
# behaviour: refresh that group on every output loop. Values above the loop
# rate naturally saturate at the loop rate; 10 kHz is a practical configuration
# ceiling for the build-time interface.
set(SCLK33_FSR_HZ "0" CACHE STRING
    "FSR acquisition target in Hz; 0 refreshes every output loop")
set(SCLK33_ACC_HZ "0" CACHE STRING
    "ACC acquisition target in Hz; 0 refreshes every output loop")
foreach(SCLK33_RATE_VAR IN ITEMS SCLK33_FSR_HZ SCLK33_ACC_HZ)
    if(NOT "${${SCLK33_RATE_VAR}}" MATCHES "^[0-9]+$")
        message(FATAL_ERROR
            "${SCLK33_RATE_VAR} must be a non-negative integer in Hz (got '${${SCLK33_RATE_VAR}}')")
    endif()
    if(${${SCLK33_RATE_VAR}} GREATER 10000)
        message(FATAL_ERROR
            "${SCLK33_RATE_VAR} must be <= 10000 Hz (got '${${SCLK33_RATE_VAR}}')")
    endif()
endforeach()

get_filename_component(
    COMBINED_BASE
    "${CMAKE_CURRENT_LIST_DIR}/../../applications/combined_system"
    ABSOLUTE
)

if(NOT EXISTS "${COMBINED_BASE}/Core/Src/main.c")
    message(FATAL_ERROR "combined_system base application not found: ${COMBINED_BASE}")
endif()

# Reuse the current board startup, HAL drivers, main loop, host DMA transport,
# protocol and linker layout. Only the acquisition translation unit below is
# replaced, so the stable combined_system source remains untouched.
add_subdirectory(
    "${COMBINED_BASE}/cmake/stm32cubemx"
    "${CMAKE_CURRENT_BINARY_DIR}/stm32cubemx"
)

if(SCLK33_PROFILE STREQUAL "stable_internal_eoc_mux_sweep")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../../applications/combined_system/Core/Src/combined_acquisition.c
    )
elseif(SCLK33_PROFILE MATCHES "^acc_")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        ../acc_rate_benchmark/combined_acquisition_acc_rate.c
    )
else()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        combined_acquisition_sclk33.c
    )
endif()

if(SCLK33_PROFILE STREQUAL "acc_hr1344")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "unused by ACC-only benchmark")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 80)
    set(ACC_BENCHMARK_DEFINES
        ACC_BENCH_MODE=1U
        ACC_BENCH_CTRL1=0x97U
        ACC_BENCH_CTRL4=0x88U)
elseif(SCLK33_PROFILE STREQUAL "acc_lp5376")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "unused by ACC-only benchmark")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 80)
    set(ACC_BENCHMARK_DEFINES
        ACC_BENCH_MODE=2U
        ACC_BENCH_CTRL1=0x9FU
        ACC_BENCH_CTRL4=0x80U)
elseif(SCLK33_PROFILE STREQUAL "safe2p5")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_32)
    set(SCLK33_SPI_DESCRIPTION "2.5 MHz")
    set(SCLK33_SETTLE_US 100)
    set(SCLK33_SETUP 0x74U)
elseif(SCLK33_PROFILE STREQUAL "legacy10_settle100")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_8)
    set(SCLK33_SPI_DESCRIPTION "10 MHz")
    set(SCLK33_SETTLE_US 100)
    set(SCLK33_SETUP 0x74U)
elseif(SCLK33_PROFILE STREQUAL "legacy10")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_8)
    set(SCLK33_SPI_DESCRIPTION "10 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x74U)
elseif(SCLK33_PROFILE STREQUAL "legacy10_refint")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "10 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 80)
elseif(SCLK33_PROFILE STREQUAL "refint5")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_32)
    set(SCLK33_SPI_DESCRIPTION "5.000 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 80)
elseif(SCLK33_PROFILE STREQUAL "refint7p5")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "7.500 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 60)
elseif(SCLK33_PROFILE STREQUAL "refint9p375")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "9.375 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 75)
elseif(SCLK33_PROFILE STREQUAL "refint8p75")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "8.750 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 70)
elseif(SCLK33_PROFILE STREQUAL "refint8p125")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "8.125 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 65)
elseif(SCLK33_PROFILE STREQUAL "refint8")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "8.000 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 64)
elseif(SCLK33_PROFILE STREQUAL "refint6p25")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "6.250 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 50)
elseif(SCLK33_PROFILE STREQUAL "refint5p625")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "5.625 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 45)
elseif(SCLK33_PROFILE STREQUAL "refint4p8125")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_32)
    set(SCLK33_SPI_DESCRIPTION "4.8125 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 77)
elseif(SCLK33_PROFILE STREQUAL "refint4p75")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_32)
    set(SCLK33_SPI_DESCRIPTION "4.750 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 76)
elseif(SCLK33_PROFILE STREQUAL "refint4p5")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_32)
    set(SCLK33_SPI_DESCRIPTION "4.500 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 72)
elseif(SCLK33_PROFILE STREQUAL "refint4")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_32)
    set(SCLK33_SPI_DESCRIPTION "4.000 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 64)
elseif(SCLK33_PROFILE STREQUAL "refint2p5")
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_64)
    set(SCLK33_SPI_DESCRIPTION "2.500 MHz")
    set(SCLK33_SETTLE_US 0)
    set(SCLK33_SETUP 0x78U)
    set(SCLK33_PLLN_VALUE 80)
elseif(SCLK33_PROFILE STREQUAL "internal_fifo_dma")
    # Internal MAX11633 conversion oscillator, external 3.3 V reference and
    # a 10 MHz data-only FIFO read. CPU=160 MHz reduces software overhead;
    # it does not change the ADC's internal conversion clock.
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_16)
    set(SCLK33_SPI_DESCRIPTION "10.000 MHz FIFO data clock")
    set(SCLK33_SETTLE_US ${INTERNAL_FIFO_MUX_SETTLE_US})
    set(SCLK33_SETUP 0x64U)
    set(SCLK33_PLLN_VALUE 80)
    set(INTERNAL_FIFO_DEFINES
        INTERNAL_FIFO_DMA_EXPERIMENT=1
        INTERNAL_FIFO_GAP_US=${INTERNAL_FIFO_GAP_US}U)
elseif(SCLK33_PROFILE STREQUAL "stable_internal_eoc_mux_sweep")
    # Reuse the stable Combined acquisition unit exactly: internal MAX11633
    # clock, 0xF8 scan, EOC qualification, and the existing Host DMA path.
    # Only the external analogue-MUX settle interval is build-time adjustable.
    set(SCLK33_SPI_DIVIDER SPI_BAUDRATEPRESCALER_8)
    set(SCLK33_SPI_DESCRIPTION "10.000 MHz FIFO data clock")
    set(SCLK33_SETTLE_US ${STABLE_EOC_MUX_SETTLE_US})
    set(SCLK33_SETUP 0x64U)
    set(STABLE_EOC_DEFINES
        FSR_MUX_SETTLE_US=${STABLE_EOC_MUX_SETTLE_US}U)
else()
    message(FATAL_ERROR
        "Unknown SCLK33_PROFILE='${SCLK33_PROFILE}'. Use safe2p5, "
        "legacy10_settle100, legacy10, legacy10_refint, refint9p375, "
        "refint8p75, refint8p125, refint8, refint7p5, "
        "refint6p25, refint5p625, refint5, "
        "refint4p8125, refint4p75, refint4p5, refint4, refint2p5, "
        "internal_fifo_dma, stable_internal_eoc_mux_sweep, "
        "acc_hr1344, or acc_lp5376.")
endif()

if(DEFINED SCLK33_PLLN_VALUE)
    set(SCLK33_SYSCLK_DEFINES
        SCLK33_SYSCLK_HIGH=1
        SCLK33_PLLN=${SCLK33_PLLN_VALUE})
    math(EXPR SCLK33_SYSCLK_MHZ "${SCLK33_PLLN_VALUE} * 2")
else()
    set(SCLK33_SYSCLK_MHZ 80)
endif()

target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    SCLK33_SPI_BAUDRATE_PRESCALER=${SCLK33_SPI_DIVIDER}
    SCLK33_MUX_SETTLE_US=${SCLK33_SETTLE_US}U
    SCLK33_SETUP_BYTE=${SCLK33_SETUP}
    SCLK33_FSR_HZ=${SCLK33_FSR_HZ}U
    SCLK33_ACC_HZ=${SCLK33_ACC_HZ}U
    ${SCLK33_SYSCLK_DEFINES}
    ${INTERNAL_FIFO_DEFINES}
    ${STABLE_EOC_DEFINES}
    ${ACC_BENCHMARK_DEFINES}
)

message(STATUS "SCLK33 profile: ${SCLK33_PROFILE}")
message(STATUS "ADC SPI1 clock: ${SCLK33_SPI_DESCRIPTION}")
message(STATUS "MUX settling: ${SCLK33_SETTLE_US} us")
message(STATUS "MAX11633 setup byte: ${SCLK33_SETUP}")
message(STATUS "STM32 SYSCLK/HCLK/APB1/APB2: ${SCLK33_SYSCLK_MHZ} MHz")
message(STATUS "FSR acquisition target: ${SCLK33_FSR_HZ} Hz (0 = every output loop)")
message(STATUS "ACC acquisition target: ${SCLK33_ACC_HZ} Hz (0 = every output loop)")
if(SCLK33_PROFILE STREQUAL "internal_fifo_dma")
    message(STATUS "Internal command-to-FIFO gap: ${INTERNAL_FIFO_GAP_US} us")
    message(STATUS "Internal external-MUX settling: ${INTERNAL_FIFO_MUX_SETTLE_US} us")
endif()

list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)
target_link_libraries(${CMAKE_PROJECT_NAME} stm32cubemx)
