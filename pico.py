#!/usr/bin/env python3
"""
Single CLI for switching Raspberry Pi Pico firmware on Linux/SSH setups.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("pyserial is required: pip install pyserial") from exc


ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_MOUNT = "/mnt/pico"
DEFAULT_PY_UF2 = ROOT / "uf2s" / "Pico-MicroPython-20250415-v1.25.0.uf2"
DEFAULT_CPP_UF2 = ROOT / "uf2s" / "bootloader_trigger.uf2"
DEFAULT_HELPER_FILES = (
    ROOT / "py" / "boot.py",
    ROOT / "py" / "bootloader_trigger.py",
)


@dataclass
class Rp2Device:
    name: str
    mountpoint: str


def parse_lsblk_line(line: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in shlex.split(line):
        key, raw_value = part.split("=", 1)
        values[key] = raw_value
    return values


def find_rpi_rp2() -> Optional[Rp2Device]:
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
    if not uf2_path.exists():
        raise RuntimeError(f"UF2 file not found: {uf2_path}")
    if verbose:
        print(f"Copying {uf2_path} -> {mountpoint}")
    shutil.copy2(uf2_path, mountpoint / uf2_path.name)
    os.sync()


def run_mpremote(args: list[str], quiet: bool = False) -> None:
    cmd = ["mpremote", *args]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=quiet,
        text=True,
    )
    if result.returncode != 0:
        err = ""
        if quiet:
            err = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"mpremote failed: {' '.join(cmd)}{(': ' + err) if err else ''}")


def wait_for_serial_port(port: str, timeout: float, verbose: bool) -> None:
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


def detect_mode(port: str, timeout: float, verbose: bool) -> Optional[str]:
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
    return mode


def trigger_from_py(port: str, verbose: bool) -> None:
    if verbose:
        print("Triggering BOOTSEL from MicroPython...")
    run_mpremote(["connect", port, "exec", "import bootloader_trigger"], quiet=not verbose)


def trigger_from_cpp(port: str, verbose: bool) -> None:
    if verbose:
        print("Triggering BOOTSEL from C++ firmware...")
    with serial.Serial(port, baudrate=115200, timeout=0.2) as ser:
        # Send both new and legacy trigger sequences for compatibility.
        ser.write(b"b")
        ser.flush()
        time.sleep(0.15)
        ser.write(b"ru")
        ser.flush()


def install_micropython_helpers(port: str, helper_files: tuple[Path, Path], verbose: bool) -> None:
    for file_path in helper_files:
        if not file_path.exists():
            raise RuntimeError(f"Missing helper file: {file_path}")
    if verbose:
        print(f"Installing MicroPython helper files to {port}...")
    for file_path in helper_files:
        run_mpremote(["connect", port, "fs", "cp", str(file_path), ":"], quiet=not verbose)


def switch_firmware(
    target: str,
    port: str,
    mode: str,
    uf2_path: Path,
    mount_base: str,
    detect_timeout: float,
    bootsel_timeout: float,
    install_helpers: bool,
    serial_wait: float,
    verbose: bool,
) -> None:
    selected_mode = mode
    if selected_mode == "auto":
        selected_mode = detect_mode(port=port, timeout=detect_timeout, verbose=verbose) or "unknown"

    if selected_mode == "py":
        trigger_from_py(port=port, verbose=verbose)
    elif selected_mode == "cpp":
        trigger_from_cpp(port=port, verbose=verbose)
    elif selected_mode == "bootsel":
        if verbose:
            print("Already in BOOTSEL mode, skipping trigger")
    else:
        raise RuntimeError(
            "Could not detect current mode. Use --mode py|cpp|bootsel to override."
        )

    mountpoint = wait_for_bootsel_mount(timeout=bootsel_timeout, mount_base=mount_base, verbose=verbose)
    copy_uf2(uf2_path=uf2_path, mountpoint=mountpoint, verbose=verbose)

    if target == "py" and install_helpers:
        wait_for_serial_port(port=port, timeout=serial_wait, verbose=verbose)
        install_micropython_helpers(port=port, helper_files=DEFAULT_HELPER_FILES, verbose=verbose)


def add_common_switch_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "py", "cpp", "bootsel"],
        help="Current firmware mode override (default: auto detect)",
    )
    parser.add_argument(
        "--mount-base",
        default=DEFAULT_MOUNT,
        help=f"Mount point to use when RPI-RP2 is not auto-mounted (default: {DEFAULT_MOUNT})",
    )
    parser.add_argument(
        "--detect-timeout",
        type=float,
        default=1.5,
        help="Seconds to wait for serial banner detection",
    )
    parser.add_argument(
        "--bootsel-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for RPI-RP2 device after trigger",
    )
    parser.add_argument(
        "--serial-wait",
        type=float,
        default=12.0,
        help="Seconds to wait for serial port after flashing",
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed logs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pico firmware switcher CLI (Linux)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_cmd = subparsers.add_parser("detect", help="Detect current Pico firmware mode")
    detect_cmd.add_argument("--port", default=DEFAULT_PORT)
    detect_cmd.add_argument("--timeout", type=float, default=1.5)
    detect_cmd.add_argument("--verbose", action="store_true")

    flash_cmd = subparsers.add_parser("flash", help="Flash a UF2 while Pico is in BOOTSEL mode")
    flash_cmd.add_argument("uf2", help="Path to UF2 file")
    flash_cmd.add_argument("--mount-base", default=DEFAULT_MOUNT)
    flash_cmd.add_argument("--bootsel-timeout", type=float, default=10.0)
    flash_cmd.add_argument("--verbose", action="store_true")

    to_py_cmd = subparsers.add_parser("to-py", help="Switch Pico to MicroPython UF2")
    add_common_switch_args(to_py_cmd)
    to_py_cmd.add_argument("--uf2", default=str(DEFAULT_PY_UF2), help="MicroPython UF2 path")
    to_py_cmd.add_argument(
        "--install-helpers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Install py/boot.py and py/bootloader_trigger.py after flashing",
    )

    to_cpp_cmd = subparsers.add_parser("to-cpp", help="Switch Pico to C++ UF2")
    add_common_switch_args(to_cpp_cmd)
    to_cpp_cmd.add_argument("--uf2", default=str(DEFAULT_CPP_UF2), help="C++ UF2 path")

    install_cmd = subparsers.add_parser(
        "install-py-files",
        help="Copy py/boot.py and py/bootloader_trigger.py to a MicroPython Pico",
    )
    install_cmd.add_argument("--port", default=DEFAULT_PORT)
    install_cmd.add_argument("--verbose", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "detect":
            mode = detect_mode(port=args.port, timeout=args.timeout, verbose=args.verbose)
            if mode:
                print(mode)
                return 0
            print("unknown")
            return 1

        if args.command == "flash":
            mountpoint = wait_for_bootsel_mount(
                timeout=args.bootsel_timeout,
                mount_base=args.mount_base,
                verbose=args.verbose,
            )
            copy_uf2(uf2_path=Path(args.uf2).expanduser(), mountpoint=mountpoint, verbose=args.verbose)
            return 0

        if args.command == "to-py":
            switch_firmware(
                target="py",
                port=args.port,
                mode=args.mode,
                uf2_path=Path(args.uf2).expanduser(),
                mount_base=args.mount_base,
                detect_timeout=args.detect_timeout,
                bootsel_timeout=args.bootsel_timeout,
                install_helpers=args.install_helpers,
                serial_wait=args.serial_wait,
                verbose=args.verbose,
            )
            return 0

        if args.command == "to-cpp":
            switch_firmware(
                target="cpp",
                port=args.port,
                mode=args.mode,
                uf2_path=Path(args.uf2).expanduser(),
                mount_base=args.mount_base,
                detect_timeout=args.detect_timeout,
                bootsel_timeout=args.bootsel_timeout,
                install_helpers=False,
                serial_wait=args.serial_wait,
                verbose=args.verbose,
            )
            return 0

        if args.command == "install-py-files":
            install_micropython_helpers(
                port=args.port,
                helper_files=DEFAULT_HELPER_FILES,
                verbose=args.verbose,
            )
            return 0

        parser.error(f"Unknown command: {args.command}")
        return 2
    except Exception as exc:  # pragma: no cover - command line error path
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
