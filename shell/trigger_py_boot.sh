#!/bin/bash

# Host script to trigger Raspberry Pi Pico into UF2 bootloader mode via MicroPython

# Set the Pico's serial device (update as needed)
PICO_DEV=$1          # First argument: Pico serial device
SHOW_OUTPUT=$2       # Second argument: Whether to show output ("true" to show)

# Check if the Pico device argument is provided
if [ -z "$PICO_DEV" ]; then
    echo "Usage: $0 <PICO_DEV> [show_output]"
    exit 1
fi

# Run the mpremote command, optionally showing output based on SHOW_OUTPUT
if [ "$SHOW_OUTPUT" = "true" ]; then
    mpremote connect "$PICO_DEV" exec "import bootloader_trigger"   # Show output
else
    mpremote connect "$PICO_DEV" exec "import bootloader_trigger" > /dev/null 2>&1  # Suppress output
fi