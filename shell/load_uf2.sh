#!/bin/bash

# This script copies a specified UF2 firmware file to a Raspberry Pi Pico mass storage device.
# Usage: ./load_uf2.sh <uf2_filename>
# The UF2 file should be located at ../uf2s/ relative to this script.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <uf2_filename>"
    exit 1
fi

UF2_FILE="$SCRIPT_DIR/../uf2s/$1"
echo "UF2 file (absolute path): $UF2_FILE"

if [[ ! -f "$UF2_FILE" ]]; then
    echo "Error: UF2 file not found at $UF2_FILE"
    exit 1
fi

PICO_DEVICE_LINE=$(lsblk -o LABEL,NAME,MOUNTPOINT -nr | awk '$1=="RPI-RP2"{print $0; exit}')
PICO_DEVICE_NAME=$(echo "$PICO_DEVICE_LINE" | awk '{print $2}')
PICO_MOUNT_POINT=$(echo "$PICO_DEVICE_LINE" | awk '{print $3}')

echo "Pico mount point: $PICO_MOUNT_POINT"

if [[ -z "$PICO_DEVICE_NAME" ]]; then
    echo "Error: Pico mass storage device (RPI-RP2) not found."
    exit 1
fi

if [[ -z "$PICO_MOUNT_POINT" ]]; then
    PICO_MOUNT_POINT="${PICO_MOUNT_BASE:-/mnt/pico}"
    echo "Pico not mounted; mounting /dev/$PICO_DEVICE_NAME at $PICO_MOUNT_POINT..."
    mkdir -p "$PICO_MOUNT_POINT"
    if ! mount "/dev/$PICO_DEVICE_NAME" "$PICO_MOUNT_POINT"; then
        echo "Error: failed to mount /dev/$PICO_DEVICE_NAME. Try running with sudo."
        exit 1
    fi
fi

echo "Copying $UF2_FILE to $PICO_MOUNT_POINT..."
cp "$UF2_FILE" "$PICO_MOUNT_POINT/"

sync

echo "Done! UF2 has been copied to the Pico."
