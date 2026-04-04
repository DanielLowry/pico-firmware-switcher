"""Static switcher-owned `boot.py` template for managed MicroPython.

This file stays fixed in the repo and is copied to the Pico device root by the
managed MicroPython sync flow. Its job is intentionally small: emit a stable
banner so the host can identify a MicroPython runtime during startup.
"""

import time

print("FW:PY")
time.sleep(0.1)
