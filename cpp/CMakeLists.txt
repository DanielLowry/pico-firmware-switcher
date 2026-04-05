cmake_minimum_required(VERSION 3.13)

# This CMake project builds the switcher-owned managed C++ runtime together
# with one selected client profile. The host-side Python tool injects the
# client source list, profile name, and desired UF2 output name via cache
# variables so one repo can build one UF2 per profile without clients owning
# `main()` or the BOOTSEL control path.

include(pico_sdk_import.cmake)

project(pico-firmware_switcher C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# These are cache variables so the host-side build tool can override them with
# `cmake -D...` for each profile-specific build directory.
set(PICO_SWITCHER_PROFILE_NAME "demo" CACHE STRING "Managed C++ profile name")
set(PICO_SWITCHER_OUTPUT_NAME "bootloader_trigger" CACHE STRING "Managed C++ UF2 output stem")
set(
    PICO_SWITCHER_BOOTSEL_COMMAND
    "BOOTSEL"
    CACHE STRING
    "Reserved text command that asks the managed runtime to enter BOOTSEL"
)
set(
    PICO_SWITCHER_CLIENT_SOURCES
    "${CMAKE_CURRENT_LIST_DIR}/../examples/demo_cpp/client_app.cpp"
    CACHE STRING
    "Semicolon-separated list of managed C++ client sources"
)

# Pull in the Pico SDK after the cache variables are declared so the rest of
# the project can consume them when targets are configured below.
pico_sdk_init()

add_executable(hello_world
    hello_world.cpp
)
target_link_libraries(hello_world pico_stdlib)

# Keep the target name stable for backwards compatibility with older scripts
# and manual build habits. The actual output filename is set independently
# below so each profile can still produce its own UF2 name.
add_executable(bootloader_trigger
    managed_runtime.cpp
    ${PICO_SWITCHER_CLIENT_SOURCES}
)
set_target_properties(bootloader_trigger PROPERTIES OUTPUT_NAME "${PICO_SWITCHER_OUTPUT_NAME}")
# The managed runtime and client sources both include `switcher_client.h`, which
# lives in this `cpp/` directory rather than in any specific client tree.
target_include_directories(bootloader_trigger PRIVATE "${CMAKE_CURRENT_LIST_DIR}")
# `pico_multicore` is required because the switcher runtime launches the client
# on core1. `pico_stdlib` provides USB stdio, timing helpers, and common SDK
# facilities used by both the runtime and client code.
target_link_libraries(bootloader_trigger pico_multicore pico_stdlib)
# Compile-time definitions make the runtime profile-aware without generating
# separate C++ source files per client profile.
target_compile_definitions(
    bootloader_trigger
    PRIVATE
        PICO_SWITCHER_PROFILE_NAME="${PICO_SWITCHER_PROFILE_NAME}"
        PICO_SWITCHER_BOOTSEL_COMMAND="${PICO_SWITCHER_BOOTSEL_COMMAND}"
)
# USB stdio is the supported host control path; UART stdio is disabled to keep
# the runtime behavior deterministic for detection and BOOTSEL commands.
pico_enable_stdio_usb(bootloader_trigger 1)
pico_enable_stdio_uart(bootloader_trigger 0)
# Generate the UF2 plus the normal extra Pico build artifacts.
pico_add_extra_outputs(bootloader_trigger)
