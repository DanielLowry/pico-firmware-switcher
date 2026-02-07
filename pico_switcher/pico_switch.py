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
    """Detect the current firmware mode: bootsel, py, cpp, or unknown."""

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
    """Best-effort mode detection that never raises."""

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
    """Switch the Pico firmware to the requested target and return whether flashing occurred."""

    selected_mode = mode
    if selected_mode == "auto":
        selected_mode = detect_mode(port=port, timeout=detect_timeout, verbose=verbose) or "unknown"

    if selected_mode == target and not force_flash:
        if verbose:
            print(f"Already in {target} mode, skipping UF2 flash.")
        if target == "py" and install_helpers:
            wait_for_serial_port(port=port, timeout=serial_wait, verbose=verbose)
            install_micropython_helpers(port=port, helper_files=helper_files, verbose=verbose)
        return False

    trigger_error: Optional[str] = None
    if selected_mode == "py":
        trigger_error = trigger_from_py(port=port, verbose=verbose)
    elif selected_mode == "cpp":
        trigger_from_cpp(port=port, verbose=verbose)
    elif selected_mode == "bootsel":
        if verbose:
            print("Already in BOOTSEL mode, skipping trigger")
    else:
        raise RuntimeError(
            "Could not detect current mode. Use --mode py|cpp|bootsel to override."
        )

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

    if target == "py" and install_helpers:
        wait_for_serial_port(port=port, timeout=serial_wait, verbose=verbose)
        install_micropython_helpers(port=port, helper_files=helper_files, verbose=verbose)
    return True
