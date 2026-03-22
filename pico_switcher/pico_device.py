"""Device I/O helpers for Pico mass-storage and serial interactions."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import serial  # type: ignore
    from serial.tools import list_ports  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("pyserial is required: pip install pyserial") from exc


@dataclass
class Rp2Device:
    """Represents a discovered RPI-RP2 block device entry."""

    name: str
    mountpoint: str


def list_serial_port_candidates() -> tuple[str, ...]:
    """Return likely USB serial device paths that could belong to a Pico."""

    candidates = sorted(
        {
            info.device
            for info in list_ports.comports()
            if info.device.startswith("/dev/ttyACM") or info.device.startswith("/dev/ttyUSB")
        }
    )
    return tuple(candidates)


def resolve_serial_port(port: str, verbose: bool) -> str:
    """Resolve a configured serial port to an existing device path.

    The CLI accepts `"auto"` to pick a single connected USB serial device.
    For compatibility, a missing `/dev/ttyACM0` also falls back to a single
    discovered candidate.
    """

    candidates = list_serial_port_candidates()

    if port == "auto":
        if len(candidates) == 1:
            if verbose:
                print(f"Using discovered serial port: {candidates[0]}")
            return candidates[0]
        if not candidates:
            raise RuntimeError(_missing_serial_port_message(port=port, candidates=candidates))
        raise RuntimeError(
            "Multiple serial ports found: "
            + ", ".join(candidates)
            + ". Use --port to select the Pico explicitly."
        )

    if Path(port).exists():
        return port

    if port == "/dev/ttyACM0" and len(candidates) == 1:
        if verbose:
            print(f"{port} not present; using discovered serial port {candidates[0]}")
        return candidates[0]

    raise RuntimeError(_missing_serial_port_message(port=port, candidates=candidates))


def _missing_serial_port_message(port: str, candidates: tuple[str, ...]) -> str:
    """Format a user-facing error for missing or ambiguous serial ports."""

    port_label = "No serial port was selected" if port == "auto" else f"Serial port not found: {port}"
    if candidates:
        return f"{port_label}. Available USB serial ports: {', '.join(candidates)}"
    return (
        f"{port_label}. No USB serial ports were detected under /dev/ttyACM* or /dev/ttyUSB*. "
        "If the Pico is already in BOOTSEL mode, use `pico.py flash ...` or `--mode bootsel`."
    )


def parse_lsblk_line(line: str) -> dict[str, str]:
    """Parse one `lsblk -P` output line into a key/value mapping.

    Args:
        line: Raw output line containing shell-quoted `KEY="VALUE"` tokens.

    Returns:
        Dictionary of parsed key/value pairs.
    """

    values: dict[str, str] = {}
    for part in shlex.split(line):
        key, raw_value = part.split("=", 1)
        values[key] = raw_value
    return values


def find_rpi_rp2() -> Optional[Rp2Device]:
    """Locate the Pico BOOTSEL mass-storage device, if present.

    Returns:
        A populated :class:`Rp2Device` when a device labeled `RPI-RP2` exists,
        else `None`.

    Raises:
        RuntimeError: If `lsblk` itself fails.
    """

    # Some lsblk versions treat --pairs (-P) as mutually exclusive with --raw (-r).
    cmd = ["lsblk", "-P", "-n", "-o", "NAME,LABEL,MOUNTPOINT"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "lsblk failed")
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        entry = parse_lsblk_line(line)
        if entry.get("LABEL") == "RPI-RP2":
            return Rp2Device(name=entry["NAME"], mountpoint=entry.get("MOUNTPOINT", ""))
    return None


def ensure_rpi_rp2_mounted(mount_base: str, verbose: bool) -> Path:
    """Return a mounted RPI-RP2 path, mounting manually if needed.

    Args:
        mount_base: Fallback mount path used if device is present but unmounted.
        verbose: Whether to print mount operations.

    Returns:
        Mountpoint path for the BOOTSEL drive.

    Raises:
        RuntimeError: If the device cannot be found or mounted.
    """

    rp2 = find_rpi_rp2()
    if rp2 is None:
        raise RuntimeError("Pico mass storage device (RPI-RP2) not found")

    if rp2.mountpoint:
        return Path(rp2.mountpoint)

    mountpoint = Path(mount_base)
    if verbose:
        print(f"Mounting /dev/{rp2.name} at {mountpoint}...")
    mountpoint.mkdir(parents=True, exist_ok=True)
    mount_cmd = ["mount", f"/dev/{rp2.name}", str(mountpoint)]
    result = subprocess.run(mount_cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "mount failed"
        raise RuntimeError(f"Failed to mount /dev/{rp2.name}: {message}")
    return mountpoint


def wait_for_bootsel_mount(timeout: float, mount_base: str, verbose: bool) -> Path:
    """Wait until the BOOTSEL drive appears and return its mountpoint.

    Args:
        timeout: Maximum time in seconds to wait.
        mount_base: Fallback mount path used when auto-mount is absent.
        verbose: Whether to print mount attempts.

    Returns:
        Mountpoint path for the BOOTSEL drive.

    Raises:
        RuntimeError: If the drive is not available before timeout.
    """

    deadline = time.time() + timeout
    last_error: Optional[str] = None
    while time.time() < deadline:
        try:
            return ensure_rpi_rp2_mounted(mount_base=mount_base, verbose=verbose)
        except RuntimeError as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise RuntimeError(last_error or "Timed out waiting for RPI-RP2")


def copy_uf2(uf2_path: Path, mountpoint: Path, verbose: bool) -> None:
    """Copy a UF2 file to the BOOTSEL drive and flush filesystem buffers.

    Args:
        uf2_path: Source UF2 file path.
        mountpoint: Mounted BOOTSEL path.
        verbose: Whether to print copy progress.

    Raises:
        RuntimeError: If the UF2 source path does not exist.
    """

    if not uf2_path.exists():
        raise RuntimeError(f"UF2 file not found: {uf2_path}")
    if verbose:
        print(f"Copying {uf2_path} -> {mountpoint}")
    shutil.copy2(uf2_path, mountpoint / uf2_path.name)
    os.sync()


def wait_for_serial_port(port: str, timeout: float, verbose: bool) -> str:
    """Wait until the expected serial device path exists.

    Args:
        port: Serial device path to watch.
        timeout: Maximum time in seconds to wait.
        verbose: Whether to print discovery status.

    Returns:
        Resolved serial device path.

    Raises:
        RuntimeError: If the port is not available before timeout.
    """

    deadline = time.time() + timeout
    last_error: Optional[str] = None
    while time.time() < deadline:
        try:
            resolved_port = resolve_serial_port(port=port, verbose=verbose)
            if verbose:
                print(f"Serial port available: {resolved_port}")
            return resolved_port
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(last_error or f"Timed out waiting for serial port: {port}")


def read_banner(
    port: str,
    baud: int = 115200,
    timeout: float = 1.0,
    verbose: bool = False,
) -> tuple[Optional[str], str]:
    """Read serial output and infer firmware mode from known banner tags.

    Args:
        port: Serial device path.
        baud: Serial baud rate.
        timeout: Maximum time in seconds to read banner output.
        verbose: Whether to print port auto-resolution details.

    Returns:
        Tuple of `(mode, last_line)` where mode is `"py"`, `"cpp"`, or `None`.
    """

    last_line = ""
    resolved_port = resolve_serial_port(port=port, verbose=verbose)
    with serial.Serial(resolved_port, baudrate=baud, timeout=0.1) as ser:
        ser.reset_input_buffer()
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="ignore").strip()
            last_line = line
            if "FW:PY" in line:
                return "py", line
            if "FW:CPP" in line:
                return "cpp", line
    return None, last_line


def trigger_from_cpp(port: str, verbose: bool) -> None:
    """Send the BOOTSEL trigger command expected by C++ firmware.

    Args:
        port: Serial device path.
        verbose: Whether to print trigger activity.
    """

    if verbose:
        print("Triggering BOOTSEL from C++ firmware...")
    resolved_port = resolve_serial_port(port=port, verbose=verbose)
    with serial.Serial(resolved_port, baudrate=115200, timeout=0.2) as ser:
        ser.write(b"b")
        ser.flush()
