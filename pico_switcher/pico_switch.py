"""Firmware switching workflow for the Pico switcher CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from .pico_device import (
    copy_uf2,
    find_rpi_rp2,
    read_banner,
    trigger_from_cpp,
    wait_for_bootsel_mount,
    wait_for_serial_port,
)
from .pico_mpremote import install_micropython_helpers, probe_micropython, trigger_from_py


def detect_mode(port: str, timeout: float, verbose: bool) -> Optional[str]:
    """Detect the current firmware mode.

    Detection order is intentionally conservative:
    1) BOOTSEL is detected from a present `RPI-RP2` mass-storage device.
    2) Runtime mode is inferred from serial banner markers (`FW:PY` / `FW:CPP`).
    3) A MicroPython probe is attempted via `mpremote`.

    Args:
        port: Serial device path used for banner reads and MicroPython probe.
        timeout: Number of seconds to listen for a serial banner.
        verbose: Whether to print detection details.

    Returns:
        `"bootsel"`, `"py"`, `"cpp"`, or `None` if no mode can be determined.
    """

    rp2 = find_rpi_rp2()
    if rp2 is not None:
        if verbose:
            print("Detected BOOTSEL mode via RPI-RP2 device")
        return "bootsel"

    mode, banner = read_banner(port=port, timeout=timeout)
    if verbose:
        if mode:
            print(f"Detected mode from serial banner: {mode} ({banner})")
        elif banner:
            print(f"No known banner found; last line seen: {banner}")
        else:
            print("No serial banner read within timeout")
    if mode:
        return mode

    if probe_micropython(port=port, verbose=verbose):
        return "py"

    return None


def detect_mode_safe(port: str, timeout: float, verbose: bool) -> Optional[str]:
    """Run :func:`detect_mode` but swallow errors.

    Args:
        port: Serial device path used for detection.
        timeout: Number of seconds to wait for banner detection.
        verbose: Whether to print suppressed detection errors.

    Returns:
        The detected mode string or `None` if detection fails.
    """

    try:
        return detect_mode(port=port, timeout=timeout, verbose=verbose)
    except Exception as exc:
        if verbose:
            print(f"Post-switch detect failed: {exc}")
        return None


def switch_firmware(
    target: str,
    port: str,
    mode: str,
    uf2_path: Path,
    mount_base: str,
    detect_timeout: float,
    bootsel_timeout: float,
    install_helpers: bool,
    helper_files: Iterable[Path],
    serial_wait: float,
    force_flash: bool,
    verbose: bool,
) -> bool:
    """Switch Pico firmware to the requested target mode.

    The workflow mirrors the original logic:
    1) Resolve current mode (auto-detected or user-provided override).
    2) If already in the target mode and not forcing a flash, skip UF2 copy.
    3) Trigger BOOTSEL from current runtime mode.
    4) Wait for RPI-RP2 mount and copy UF2.
    5) Optionally install MicroPython helper files after boot.

    Args:
        target: Desired target firmware (`"py"` or `"cpp"`).
        port: Serial device path used for trigger and helper install.
        mode: Current mode override (`"auto"`, `"py"`, `"cpp"`, `"bootsel"`).
        uf2_path: UF2 file to flash.
        mount_base: Mount path used if RPI-RP2 is not auto-mounted.
        detect_timeout: Banner detection timeout for auto mode resolution.
        bootsel_timeout: Timeout while waiting for BOOTSEL mass storage.
        install_helpers: Whether to copy helper files after a MicroPython target boot.
        helper_files: Files to copy when helper installation is enabled.
        serial_wait: Timeout while waiting for serial port after flash.
        force_flash: Flash even if current mode already equals target.
        verbose: Whether to print detailed operation logs.

    Returns:
        `True` when a UF2 was flashed, `False` when flash was skipped.

    Raises:
        RuntimeError: If mode cannot be resolved, BOOTSEL trigger fails, mount fails,
            or helper installation prerequisites are missing.
    """

    selected_mode = mode
    if selected_mode == "auto":
        selected_mode = detect_mode(port=port, timeout=detect_timeout, verbose=verbose) or "unknown"

    if selected_mode == target and not force_flash:
        if verbose:
            print(f"Already in {target} mode, skipping UF2 flash.")
        _install_helpers_if_requested(
            target=target,
            install_helpers=install_helpers,
            port=port,
            helper_files=helper_files,
            serial_wait=serial_wait,
            verbose=verbose,
        )
        return False

    trigger_error = _trigger_bootsel(selected_mode=selected_mode, port=port, verbose=verbose)

    try:
        mountpoint = wait_for_bootsel_mount(
            timeout=bootsel_timeout,
            mount_base=mount_base,
            verbose=verbose,
        )
    except RuntimeError as exc:
        if trigger_error:
            raise RuntimeError(f"MicroPython trigger failed: {trigger_error}") from exc
        raise
    copy_uf2(uf2_path=uf2_path, mountpoint=mountpoint, verbose=verbose)

    _install_helpers_if_requested(
        target=target,
        install_helpers=install_helpers,
        port=port,
        helper_files=helper_files,
        serial_wait=serial_wait,
        verbose=verbose,
    )
    return True


def _trigger_bootsel(selected_mode: str, port: str, verbose: bool) -> Optional[str]:
    """Trigger BOOTSEL based on the currently running firmware mode.

    Args:
        selected_mode: Resolved current mode (`"py"`, `"cpp"`, or `"bootsel"`).
        port: Serial device path used for trigger commands.
        verbose: Whether to print trigger status.

    Returns:
        Error text from MicroPython trigger attempts, else `None`.

    Raises:
        RuntimeError: If `selected_mode` is unknown.
    """

    if selected_mode == "py":
        return trigger_from_py(port=port, verbose=verbose)
    if selected_mode == "cpp":
        trigger_from_cpp(port=port, verbose=verbose)
        return None
    if selected_mode == "bootsel":
        if verbose:
            print("Already in BOOTSEL mode, skipping trigger")
        return None
    raise RuntimeError("Could not detect current mode. Use --mode py|cpp|bootsel to override.")


def _install_helpers_if_requested(
    target: str,
    install_helpers: bool,
    port: str,
    helper_files: Iterable[Path],
    serial_wait: float,
    verbose: bool,
) -> None:
    """Install MicroPython helper files when target and flags require it."""

    if target != "py" or not install_helpers:
        return
    wait_for_serial_port(port=port, timeout=serial_wait, verbose=verbose)
    install_micropython_helpers(port=port, helper_files=helper_files, verbose=verbose)
