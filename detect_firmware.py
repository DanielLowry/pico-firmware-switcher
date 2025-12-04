#!/usr/bin/env python3
"""
Quickly report whether the Pico is running MicroPython or the C++ firmware
by reading the startup banner over serial. Requires `pyserial`.
"""

import sys
import time
from typing import Optional, Tuple

try:
    import serial  # type: ignore
except ImportError as exc:
    raise SystemExit("pyserial is required: pip install pyserial") from exc


def read_banner(port: str, baud: int = 115200, timeout: float = 1.0) -> Tuple[Optional[str], str]:
    """Read lines for up to `timeout` seconds and return (mode, last_line)."""
    last_line = ""
    with serial.Serial(port, baudrate=baud, timeout=0.1) as ser:
        ser.reset_input_buffer()
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="ignore").strip()
            last_line = line
            if "FW:PY" in line:
                return "MicroPython", line
            if "FW:CPP" in line:
                return "C++", line
    return None, last_line


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
    mode, banner = read_banner(port)
    if mode:
        print(f"{mode} detected on {port} ({banner})")
        return 0
    if banner:
        print(f"Unknown firmware on {port}; last line seen: {banner}")
    else:
        print(f"No banner read from {port} within timeout")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
