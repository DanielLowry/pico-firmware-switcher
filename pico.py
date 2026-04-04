#!/usr/bin/env python3
"""
Repository entrypoint for the Pico switcher command-line interface.

This thin wrapper keeps the user-facing invocation stable as `python pico.py ...`
while delegating all argument parsing and behavior to the package implementation
in `pico_switcher.pico_cli`.
"""

from __future__ import annotations

from pico_switcher.pico_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
