#!/bin/bash

# Copy MicroPython helper files onto the Pico filesystem via mpremote.
# Usage: ./install_micropython_files.sh <PICO_DEV>
# Example: ./install_micropython_files.sh /dev/ttyACM0

set -e

PICO_DEV=$1

if [ -z "$PICO_DEV" ]; then
    echo "Usage: $0 <PICO_DEV>"
    echo "Usually this is /dev/ttyACM0 (or similar)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PY_DIR="$SCRIPT_DIR/../py"

if [[ ! -f "$PY_DIR/boot.py" || ! -f "$PY_DIR/bootloader_trigger.py" ]]; then
    echo "Error: expected boot.py and bootloader_trigger.py in $PY_DIR"
    exit 1
fi

mpremote connect "$PICO_DEV" fs cp "$PY_DIR/boot.py" :
mpremote connect "$PICO_DEV" fs cp "$PY_DIR/bootloader_trigger.py" :

echo "Installed MicroPython helper files onto Pico."
