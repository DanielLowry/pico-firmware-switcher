"""Prototype MicroPython helper that enters BOOTSEL from the device runtime.

The current switch flow can import this helper over `mpremote` to request UF2
bootloader mode from a running MicroPython image. Later phases plan to replace
this client-visible helper with a host-driven `mpremote bootloader` action.
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
