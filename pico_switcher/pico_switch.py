"""Firmware switching workflow for the Pico switcher CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from . import PROJECT_ROOT
from .pico_device import (
    copy_uf2,
    find_rpi_rp2,
    read_banner,
    trigger_from_cpp,
    wait_for_bootsel_mount,
    wait_for_serial_port,
)
from .pico_log import EventRecorder
from .pico_mpremote import DEFAULT_HELPER_FILES, install_micropython_helpers, probe_micropython, trigger_from_py


DEFAULT_MODE = "auto"
DEFAULT_DETECT_TIMEOUT = 1.5
DEFAULT_BOOTSEL_TIMEOUT = 10.0
DEFAULT_SERIAL_WAIT = 12.0
DEFAULT_INSTALL_HELPERS = True
MIN_POST_SWITCH_DETECT_TIMEOUT = 2.0
DEFAULT_PY_UF2 = PROJECT_ROOT / "uf2s" / "Pico-MicroPython-20250415-v1.25.0.uf2"
DEFAULT_CPP_UF2 = PROJECT_ROOT / "uf2s" / "bootloader_trigger.uf2"


def detect_mode(
    port: str,
    timeout: float,
    verbose: bool,
    recorder: Optional[EventRecorder] = None,
    reason: str = "detect",
) -> Optional[str]:
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
        if recorder is not None:
            recorder.event(
                "detect_mode",
                mode="bootsel",
                port=port,
                mountpoint=rp2.mountpoint or None,
                message="Detected BOOTSEL mode via RPI-RP2 device",
                details={
                    "reason": reason,
                    "device": rp2.name,
                },
            )
        return "bootsel"

    mode, banner = read_banner(port=port, timeout=timeout, verbose=verbose)
    if verbose:
        if mode:
            print(f"Detected mode from serial banner: {mode} ({banner})")
        elif banner:
            print(f"No known banner found; last line seen: {banner}")
        else:
            print("No serial banner read within timeout")
    if mode:
        if recorder is not None:
            recorder.event(
                "detect_mode",
                mode=mode,
                port=port,
                message="Detected firmware mode from serial banner",
                details={
                    "reason": reason,
                    "banner": banner,
                },
            )
        return mode

    if probe_micropython(port=port, verbose=verbose):
        if recorder is not None:
            recorder.event(
                "detect_mode",
                mode="py",
                port=port,
                message="Detected MicroPython via mpremote probe",
                details={"reason": reason},
            )
        return "py"

    if recorder is not None:
        recorder.event(
            "detect_mode",
            status="unknown",
            port=port,
            message="Could not determine Pico firmware mode",
            details={
                "reason": reason,
                "last_banner": banner or None,
            },
        )
    return None


def detect_mode_safe(
    port: str,
    timeout: float,
    verbose: bool,
    recorder: Optional[EventRecorder] = None,
    reason: str = "detect_safe",
) -> Optional[str]:
    """Run :func:`detect_mode` but swallow errors.

    Args:
        port: Serial device path used for detection.
        timeout: Number of seconds to wait for banner detection.
        verbose: Whether to print suppressed detection errors.

    Returns:
        The detected mode string or `None` if detection fails.
    """

    try:
        return detect_mode(
            port=port,
            timeout=timeout,
            verbose=verbose,
            recorder=recorder,
            reason=reason,
        )
    except Exception as exc:
        if verbose:
            print(f"Post-switch detect failed: {exc}")
        if recorder is not None:
            recorder.event(
                "detect_mode",
                status="error",
                port=port,
                message=str(exc),
                details={"reason": reason},
            )
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
    helper_files: Optional[Iterable[Path]],
    serial_wait: float,
    force_flash: bool,
    verbose: bool,
    recorder: Optional[EventRecorder] = None,
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
        helper_files: Files to copy when helper installation is enabled. When `None`,
            the bundled MicroPython helper files are used.
        serial_wait: Timeout while waiting for serial port after flash.
        force_flash: Flash even if current mode already equals target.
        verbose: Whether to print detailed operation logs.

    Returns:
        `True` when a UF2 was flashed, `False` when flash was skipped.

    Raises:
        RuntimeError: If mode cannot be resolved, BOOTSEL trigger fails, mount fails,
            or helper installation prerequisites are missing.
    """

    resolved_helper_files = tuple(helper_files or DEFAULT_HELPER_FILES)

    if recorder is not None:
        recorder.event(
            "switch_requested",
            target_mode=target,
            port=port,
            message="Firmware switch requested",
            details={
                "mode_override": mode,
                "force_flash": force_flash,
                "uf2_path": str(uf2_path),
            },
        )

    selected_mode = mode
    if selected_mode == "auto":
        selected_mode = (
            detect_mode(
                port=port,
                timeout=detect_timeout,
                verbose=verbose,
                recorder=recorder,
                reason="switch_preflight",
            )
            or "unknown"
        )

    if selected_mode == target and not force_flash:
        if verbose:
            print(f"Already in {target} mode, skipping UF2 flash.")
        if recorder is not None:
            recorder.event(
                "switch_skipped",
                mode=selected_mode,
                target_mode=target,
                port=port,
                message="Device already in target mode; skipped UF2 flash",
                details={"uf2_path": str(uf2_path)},
            )
        _install_helpers_if_requested(
            target=target,
            install_helpers=install_helpers,
            port=port,
            helper_files=resolved_helper_files,
            serial_wait=serial_wait,
            verbose=verbose,
            recorder=recorder,
        )
        return False

    try:
        trigger_error = _trigger_bootsel(selected_mode=selected_mode, port=port, verbose=verbose)
    except Exception as exc:
        if recorder is not None:
            recorder.event(
                "bootsel_trigger",
                status="error",
                mode=selected_mode,
                target_mode=target,
                port=port,
                message=str(exc),
            )
        raise
    if recorder is not None:
        recorder.event(
            "bootsel_trigger",
            status="warning" if trigger_error else "ok",
            mode=selected_mode,
            target_mode=target,
            port=port,
            message=trigger_error or "Requested BOOTSEL transition",
        )

    try:
        mountpoint = wait_for_bootsel_mount(
            timeout=bootsel_timeout,
            mount_base=mount_base,
            verbose=verbose,
        )
    except RuntimeError as exc:
        if recorder is not None:
            recorder.event(
                "bootsel_mount",
                status="error",
                target_mode=target,
                port=port,
                message=str(exc),
                details={"mount_base": mount_base},
            )
        if trigger_error:
            raise RuntimeError(f"MicroPython trigger failed: {trigger_error}") from exc
        raise
    if recorder is not None:
        recorder.event(
            "bootsel_mount",
            mode="bootsel",
            target_mode=target,
            port=port,
            mountpoint=str(mountpoint),
            message="BOOTSEL mass-storage device is ready",
            details={"mount_base": mount_base},
        )
    try:
        copy_uf2(uf2_path=uf2_path, mountpoint=mountpoint, verbose=verbose)
    except Exception as exc:
        if recorder is not None:
            recorder.event(
                "uf2_flash",
                status="error",
                target_mode=target,
                port=port,
                mountpoint=str(mountpoint),
                message=str(exc),
                details={"uf2_path": str(uf2_path)},
            )
        raise
    if recorder is not None:
        recorder.event(
            "uf2_flash",
            target_mode=target,
            port=port,
            mountpoint=str(mountpoint),
            message=f"Flashed {uf2_path.name}",
            details={"uf2_path": str(uf2_path)},
        )

    _install_helpers_if_requested(
        target=target,
        install_helpers=install_helpers,
        port=port,
        helper_files=resolved_helper_files,
        serial_wait=serial_wait,
        verbose=verbose,
        recorder=recorder,
    )
    if recorder is not None:
        recorder.event(
            "switch_completed",
            target_mode=target,
            port=port,
            message="Firmware switch workflow completed",
            details={"uf2_path": str(uf2_path)},
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
    recorder: Optional[EventRecorder] = None,
) -> None:
    """Install MicroPython helper files when target and flags require it."""

    if target != "py" or not install_helpers:
        return
    try:
        resolved_port = wait_for_serial_port(port=port, timeout=serial_wait, verbose=verbose)
        install_micropython_helpers(port=resolved_port, helper_files=helper_files, verbose=verbose)
    except Exception as exc:
        if recorder is not None:
            recorder.event(
                "helpers_install",
                status="error",
                target_mode=target,
                port=port,
                message=str(exc),
                details={"helper_files": [str(file_path) for file_path in helper_files]},
            )
        raise
    if recorder is not None:
        recorder.event(
            "helpers_install",
            target_mode=target,
            port=resolved_port,
            message="Installed MicroPython helper files",
            details={"helper_files": [str(file_path) for file_path in helper_files]},
        )
