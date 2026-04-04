"""Switcher-owned MicroPython boot hook used by the prototype runtime.

This file is copied to the Pico so the host can identify a MicroPython runtime
from a stable startup banner. Later managed-profile phases will expand this
switcher-owned root file role rather than handing it to client code.
"""

import time

print("FW:PY")
time.sleep(0.1)
