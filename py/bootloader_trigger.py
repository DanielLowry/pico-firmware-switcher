# This script is designed to reboot the Raspberry Pi Pico into bootloader mode.

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