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
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("pyserial is required: pip install pyserial") from exc


@dataclass
class Rp2Device:
    """Represents a discovered RPI-RP2 block device entry."""

    name: str
    mountpoint: str


def parse_lsblk_line(line: str) -> dict[str, str]:
    """Parse one `lsblk -P` output line into a key/value mapping."""

    values: dict[str, str] = {}
    for part in shlex.split(line):
        key, raw_value = part.split("=", 1)
        values[key] = raw_value
    return values


def find_rpi_rp2() -> Optional[Rp2Device]:
    """Locate the Pico BOOTSEL mass-storage device, if present."""

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
    """Return a mounted RPI-RP2 path, mounting manually if needed."""

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
    """Wait for the RPI-RP2 drive to appear and return its mountpoint."""

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
    """Copy a UF2 file to the mounted RPI-RP2 volume and flush buffers."""

    if not uf2_path.exists():
        raise RuntimeError(f"UF2 file not found: {uf2_path}")
    if verbose:
        print(f"Copying {uf2_path} -> {mountpoint}")
    shutil.copy2(uf2_path, mountpoint / uf2_path.name)
    os.sync()


def wait_for_serial_port(port: str, timeout: float, verbose: bool) -> None:
    """Wait until the serial device path exists."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        if Path(port).exists():
            if verbose:
                print(f"Serial port available: {port}")
            return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for serial port: {port}")


def read_banner(
    port: str,
    baud: int = 115200,
    timeout: float = 1.0,
) -> tuple[Optional[str], str]:
    """Read serial lines briefly and infer firmware mode from banner tags."""

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
                return "py", line
            if "FW:CPP" in line:
                return "cpp", line
    return None, last_line


def trigger_from_cpp(port: str, verbose: bool) -> None:
    """Send the BOOTSEL trigger sequence expected by C++ firmware."""

    if verbose:
        print("Triggering BOOTSEL from C++ firmware...")
    with serial.Serial(port, baudrate=115200, timeout=0.2) as ser:
        # Send both new and legacy trigger sequences for compatibility.
        ser.write(b"b")
        ser.flush()
        time.sleep(0.15)
        ser.write(b"ru")
        ser.flush()
