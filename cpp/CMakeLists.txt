cmake_minimum_required(VERSION 3.13)

# initialize the SDK based on PICO_SDK_PATH
# note: this must happen before project()
include(pico_sdk_import.cmake)

project(pico-firmware_switcher)

# initialize the Raspberry Pi Pico SDK
pico_sdk_init()

# hello world - just for testing
add_executable(hello_world
    hello_world.cpp
)

# bootloader trigger - program which switches into UF2 bootloader mode when user hits specific key combination
add_executable(bootloader_trigger
    bootloader_trigger.cpp
)

# Add pico_stdlib library which aggregates commonly used features
target_link_libraries(hello_world pico_stdlib)
target_link_libraries(bootloader_trigger pico_stdlib)

# create map/bin/hex/uf2 file in addition to ELF.
pico_add_extra_outputs(bootloader_trigger)