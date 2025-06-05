#!/bin/bash

# Host script to trigger Raspberry Pi Pico into UF2 bootloader mode via MicroPython

# Set the Pico's serial device (update as needed)
PICO_DEV=$1

# Use ampy or mpremote to run the script on the Pico
# Uncomment one of the following blocks depending on your tool

# Using mpremote (recommended for newer MicroPython versions)
mpremote connect $PICO_DEV run "import bootloader_trigger"