#!/bin/bash

# This script copies the MicroPython UF2 firmware to a Raspberry Pi Pico mass storage device.
# The UF2 file path is resolved relative to the script's location, not the current working directory.
# The UF2 file is located relative to this script at ../uf2s/micropython.uf2
# The Pico appears as a USB mass storage device with the volume label "RPI-RP2".

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
echo $SCRIPT_DIR
"$SCRIPT_DIR/load_uf2.sh" Pico-MicroPython-20250415-v1.25.0.uf2