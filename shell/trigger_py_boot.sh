#!/bin/bash

# Host script to trigger Raspberry Pi Pico into UF2 bootloader mode via MicroPython

# Set the Pico's serial device (update as needed)
PICO_DEV=$1

# Using mpremote (recommended for newer MicroPython versions)
mpremote connect $PICO_DEV exec "import bootloader_trigger" > /dev/null 2>&1