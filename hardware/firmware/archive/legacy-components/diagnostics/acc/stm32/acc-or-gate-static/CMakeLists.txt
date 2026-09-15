cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)


# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME ESKIN_STM32)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Select one physical ACC and one static MOSI level for OR-gate probing.
set(ACC_SELECTED "1" CACHE STRING "Physical ACC branch to hold selected: 1..9")
if(NOT ACC_SELECTED MATCHES "^[0-9]+$")
    message(FATAL_ERROR "ACC_SELECTED must be an integer from 1 to 9")
endif()
if(ACC_SELECTED LESS 1 OR ACC_SELECTED GREATER 9)
    message(FATAL_ERROR "ACC_SELECTED must be in the range 1..9")
endif()
set(OR_GATE_MOSI_LEVEL "1" CACHE STRING "Static MOSI level: 0=low, 1=high")
if(NOT OR_GATE_MOSI_LEVEL MATCHES "^[01]$")
    message(FATAL_ERROR "OR_GATE_MOSI_LEVEL must be 0 or 1")
endif()
message(STATUS "OR-gate static test: ACC${ACC_SELECTED}, MOSI=${OR_GATE_MOSI_LEVEL}")

# Enable CMake support for ASM and C languages
enable_language(C ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user sources here
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined include paths
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    ACC_SELECTED=${ACC_SELECTED}
    OR_GATE_MOSI_LEVEL=${OR_GATE_MOSI_LEVEL}
)

# Remove wrong libob.a library dependency when using cpp files
list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx

    # Add user defined libraries
)
