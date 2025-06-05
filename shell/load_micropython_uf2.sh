#!/bin/bash

# This script copies the MicroPython UF2 firmware to a Raspberry Pi Pico mass storage device.
# The UF2 file path is resolved relative to the script's location, not the current working directory.
# The UF2 file is located relative to this script at ../uf2s/micropython.uf2
# The Pico appears as a USB mass storage device with the volume label "RPI-RP2".

set -e

# Get the absolute path of the directory containing this shell script (not the current working directory).
# This is achieved by:
# 1. Using "$0" to get the path of the script being executed.
# 2. Passing "$0" to dirname to extract the directory portion.
# 3. Using cd to change to that directory.
# 4. Using pwd to print the absolute path of that directory.
# The result is stored in SCRIPT_DIR, which can be used to reference files relative to the script's location.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Script directory: $SCRIPT_DIR"

# Define the path to the UF2 file relative to the script directory
UF2_FILE="$SCRIPT_DIR/../uf2s/Pico-MicroPython-20250415-v1.25.0.uf2"
echo "UF2 file (absolute path): $UF2_FILE"

# Check if the UF2 file exists
if [[ ! -f "$UF2_FILE" ]]; then
    echo "Error: UF2 file not found at $UF2_FILE"
    exit 1
fi

# Find the mount point for the Pico (volume label RPI-RP2)
# awk automatically splits text by whitespace, so we can use it to extract the mount point
# lsblk lists block devices, -o LABEL,MOUNTPOINT shows only the label and mount point
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