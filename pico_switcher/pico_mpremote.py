"""mpremote command helpers for interacting with MicroPython."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Optional


def _format_mpremote_error(result: subprocess.CompletedProcess[str]) -> str:
    """Extract a readable error message from a completed mpremote process."""

    return (result.stderr or result.stdout or "").strip()


def run_mpremote(
    args: list[str],
    quiet: bool = False,
    allow_error: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run mpremote and optionally raise if the command fails."""

    cmd = ["mpremote", *args]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=quiet,
        text=True,
    )
    if result.returncode != 0 and not allow_error:
        err = ""
        if quiet:
            err = _format_mpremote_error(result)
        raise RuntimeError(f"mpremote failed: {' '.join(cmd)}{(': ' + err) if err else ''}")
    return result


def probe_micropython(port: str, verbose: bool) -> bool:
    """Try a tiny mpremote exec to confirm MicroPython is responding."""

    result = run_mpremote(
        ["connect", port, "exec", "print('FW:PY')"],
        quiet=True,
        allow_error=True,
    )
    if result.returncode == 0:
        if verbose:
            print("Detected MicroPython via mpremote probe")
        return True
    if verbose:
        err = _format_mpremote_error(result)
        if err:
            print(f"mpremote probe failed: {err}")
    return False


def trigger_from_py(port: str, verbose: bool) -> Optional[str]:
    """Ask MicroPython to enter BOOTSEL mode using the helper module."""

    if verbose:
        print("Triggering BOOTSEL from MicroPython...")
    result = run_mpremote(
        ["connect", port, "exec", "import bootloader_trigger"],
        quiet=not verbose,
        allow_error=True,
    )
    if result.returncode == 0:
        return None
    err = _format_mpremote_error(result)
    if verbose and err:
        print(f"mpremote trigger warning: {err}")
    return err or "mpremote failed to run bootloader_trigger"


def install_micropython_helpers(
    port: str,
    helper_files: Iterable[Path],
    verbose: bool,
) -> None:
    """Copy helper files to a MicroPython device using mpremote."""

    for file_path in helper_files:
        if not file_path.exists():
            raise RuntimeError(f"Missing helper file: {file_path}")
    if verbose:
        print(f"Installing MicroPython helper files to {port}...")
    for file_path in helper_files:
        run_mpremote(["connect", port, "fs", "cp", str(file_path), ":"], quiet=not verbose)
