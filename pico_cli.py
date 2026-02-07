"""Argument parsing and command dispatch for the Pico switcher CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pico_mpremote import install_micropython_helpers
from pico_device import copy_uf2, wait_for_bootsel_mount
from pico_switch import detect_mode, detect_mode_safe, switch_firmware


ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_MOUNT = "/mnt/pico"
DEFAULT_PY_UF2 = ROOT / "uf2s" / "Pico-MicroPython-20250415-v1.25.0.uf2"
DEFAULT_CPP_UF2 = ROOT / "uf2s" / "bootloader_trigger.uf2"
DEFAULT_HELPER_FILES = (
    ROOT / "py" / "boot.py",
    ROOT / "py" / "bootloader_trigger.py",
)


def add_common_switch_args(parser: argparse.ArgumentParser) -> None:
    """Register arguments shared by the to-py and to-cpp subcommands."""

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
    parser.add_argument(
        "--force-flash",
        action="store_true",
        help="Flash even when detect reports device already in target mode",
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed logs")


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI parser with subcommands."""

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
    """CLI entrypoint for Pico firmware switching."""

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
            flashed = switch_firmware(
                target="py",
                port=args.port,
                mode=args.mode,
                uf2_path=Path(args.uf2).expanduser(),
                mount_base=args.mount_base,
                detect_timeout=args.detect_timeout,
                bootsel_timeout=args.bootsel_timeout,
                install_helpers=args.install_helpers,
                helper_files=DEFAULT_HELPER_FILES,
                serial_wait=args.serial_wait,
                force_flash=args.force_flash,
                verbose=args.verbose,
            )
            if flashed:
                print("Switched to MicroPython UF2.")
            else:
                print("Already in MicroPython mode; skipped UF2 flash.")
            detect_timeout = max(args.detect_timeout, 2.0)
            mode = detect_mode_safe(port=args.port, timeout=detect_timeout, verbose=args.verbose)
            print(f"detect: {mode or 'unknown'}")
            return 0

        if args.command == "to-cpp":
            flashed = switch_firmware(
                target="cpp",
                port=args.port,
                mode=args.mode,
                uf2_path=Path(args.uf2).expanduser(),
                mount_base=args.mount_base,
                detect_timeout=args.detect_timeout,
                bootsel_timeout=args.bootsel_timeout,
                install_helpers=False,
                helper_files=DEFAULT_HELPER_FILES,
                serial_wait=args.serial_wait,
                force_flash=args.force_flash,
                verbose=args.verbose,
            )
            if flashed:
                print("Switched to C++ UF2.")
            else:
                print("Already in C++ mode; skipped UF2 flash.")
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
