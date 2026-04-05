"""Thin public facade for the Pico switcher CLI.

The full CLI implementation now lives in `pico_switcher.cli.*`. This module
exists to keep `from pico_switcher.pico_cli import main` stable for the repo
entrypoint and any external callers that import the package-level CLI entry.
"""

from __future__ import annotations

from .cli.runner import run_cli


def main() -> int:
    """Run the CLI using the refactored package implementation."""

    return run_cli()
