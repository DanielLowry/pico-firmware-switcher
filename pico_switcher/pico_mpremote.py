"""mpremote command helpers for interacting with MicroPython."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Optional


def _format_mpremote_error(result: subprocess.CompletedProcess[str]) -> str:
    """Extract the most useful error text from a completed `mpremote` process."""

    return (result.stderr or result.stdout or "").strip()


def run_mpremote(
    args: list[str],
    quiet: bool = False,
    allow_error: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run `mpremote` and optionally raise on non-zero exit.

    Args:
        args: Arguments passed to `mpremote`.
        quiet: If `True`, capture stdout/stderr for controlled error reporting.
        allow_error: If `True`, return failures instead of raising.

    Returns:
        The completed process object.

    Raises:
        RuntimeError: If `mpremote` fails and `allow_error` is `False`.
    """

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
    """Probe the device for a responding MicroPython runtime.

    Args:
        port: Serial device path for `mpremote connect`.
        verbose: Whether to print probe diagnostics.

    Returns:
        `True` when a minimal `mpremote exec` succeeds, otherwise `False`.
    """

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
    """Ask MicroPython firmware to enter BOOTSEL mode.

    Args:
        port: Serial device path for `mpremote connect`.
        verbose: Whether to print trigger diagnostics.

    Returns:
        `None` on success, otherwise a user-facing error summary.
    """

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
    """Copy helper files to a MicroPython filesystem via `mpremote`.

    Args:
        port: Serial device path for `mpremote connect`.
        helper_files: Paths that must exist locally before copy.
        verbose: Whether to print install progress.

    Raises:
        RuntimeError: If any helper file path is missing or copy fails.
    """

    resolved_files = _require_helper_files(helper_files)
    if verbose:
        print(f"Installing MicroPython helper files to {port}...")
    for file_path in resolved_files:
        run_mpremote(["connect", port, "fs", "cp", str(file_path), ":"], quiet=not verbose)


def _require_helper_files(helper_files: Iterable[Path]) -> tuple[Path, ...]:
    """Materialize and validate helper file paths before copy operations."""

    resolved_files = tuple(helper_files)
    for file_path in resolved_files:
        if not file_path.exists():
            raise RuntimeError(f"Missing helper file: {file_path}")
    return resolved_files
