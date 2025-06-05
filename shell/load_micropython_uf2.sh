#!/bin/bash

# This script copies the MicroPython UF2 firmware to a Raspberry Pi Pico mass storage device.
# The UF2 file is located relative to this script at ../uf2s/micropython.uf2
# The Pico appears as a USB mass storage device with the volume label "RPI-RP2".

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Define the path to the UF2 file relative to the script directory
UF2_FILE="$SCRIPT_DIR/../uf2s/micropython.uf2"
RELATIVE_UF2_FILE="../uf2s/micropython.uf2"

echo "UF2 file (relative path): $RELATIVE_UF2_FILE"

# Check if the UF2 file exists
if [[ ! -f "$UF2_FILE" ]]; then
    echo "Error: UF2 file not found at $UF2_FILE"
    exit 1
fi

# Find the mount point for the Pico (volume label RPI-RP2)
PICO_MOUNT_POINT=$(lsblk -o LABEL,MOUNTPOINT | grep 'RPI-RP2' | awk '{print $2}')

echo "Pico mount point: $PICO_MOUNT_POINT"

# Check if the Pico is mounted
if [[ -z "$PICO_MOUNT_POINT" ]]; then
    echo "Error: Pico mass storage device (RPI-RP2) not found."
    exit 1
fi

# Copy the UF2 file to the Pico's mount point
echo "Copying $UF2_FILE to $PICO_MOUNT_POINT..."
cp "$UF2_FILE" "$PICO_MOUNT_POINT/"

# Sync to ensure the file is written before the Pico reboots
sync

echo "Done! MicroPython UF2 has been copied to the Pico."