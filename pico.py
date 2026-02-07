#!/usr/bin/env python3
"""
Single CLI for switching Raspberry Pi Pico firmware on Linux/SSH setups.
"""

from __future__ import annotations

from pico_switcher.pico_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
