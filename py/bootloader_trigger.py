"""Legacy MicroPython helper that enters BOOTSEL from the device runtime.

The supported host path now uses `mpremote bootloader` directly instead of
importing this helper on the device. This file remains as a reference for the
older prototype flow and for any remaining legacy shell helpers.
"""

try:
    import machine, time

    # small delay to let any pending I/O flush
    time.sleep(0.1)
    machine.bootloader()

except ImportError:
    # If running on a platform that does not support machine module
    print("This script is intended to run on a Raspberry Pi Pico or similar device.")
    print("It cannot be executed in this environment.")
    raise SystemExit(1)
