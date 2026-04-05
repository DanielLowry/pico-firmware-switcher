"""Argument parser construction for the Pico switcher CLI.

This module defines the user-facing command shape and option defaults. It does
not execute commands; it only builds the argparse tree used by the runner.
"""

from __future__ import annotations

import argparse

from ..pico_backup import default_backup_config_path
from ..pico_device import DEFAULT_MOUNT_BASE, DEFAULT_PORT, SERIAL_PORT_HELP
from ..pico_log import DEFAULT_SNAPSHOT_SOURCE, default_db_path
from ..pico_profiles import CONFIG_FILE_NAME, SwitcherConfig
from ..pico_switch import DEFAULT_BOOTSEL_TIMEOUT, DEFAULT_DETECT_TIMEOUT, DEFAULT_MODE, DEFAULT_SERIAL_WAIT
from ..pico_systemd import DEFAULT_SERVICE_NAME, DEFAULT_TIMER_INTERVAL, DEFAULT_UNIT_DIR


def add_common_switch_args(
    parser: argparse.ArgumentParser,
    *,
    default_port: str,
    default_mount_base: str,
) -> None:
    """Register CLI arguments shared by `to-py` and `to-cpp`."""

    parser.add_argument("--port", default=default_port, help=f"{SERIAL_PORT_HELP} (default: {default_port})")
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        choices=["auto", "py", "cpp", "bootsel"],
        help=f"Current firmware mode override (default: {DEFAULT_MODE})",
    )
    parser.add_argument(
        "--mount-base",
        default=default_mount_base,
        help=f"Mount point to use when RPI-RP2 is not auto-mounted (default: {default_mount_base})",
    )
    parser.add_argument(
        "--detect-timeout",
        type=float,
        default=DEFAULT_DETECT_TIMEOUT,
        help="Seconds to wait for serial banner detection",
    )
    parser.add_argument(
        "--bootsel-timeout",
        type=float,
        default=DEFAULT_BOOTSEL_TIMEOUT,
        help="Seconds to wait for RPI-RP2 device after trigger",
    )
    parser.add_argument(
        "--serial-wait",
        type=float,
        default=DEFAULT_SERIAL_WAIT,
        help="Seconds to wait for serial port after flashing",
    )
    parser.add_argument(
        "--force-flash",
        action="store_true",
        help="Flash even when detect reports device already in target mode",
    )
    add_db_arg(parser)
    parser.add_argument("--verbose", action="store_true", help="Show detailed logs")


def add_config_arg(parser: argparse.ArgumentParser) -> None:
    """Register the shared config file option."""

    parser.add_argument(
        "--config",
        help=f"Path to {CONFIG_FILE_NAME}; defaults to env or upward search",
    )


def add_profile_arg(parser: argparse.ArgumentParser, config: SwitcherConfig) -> None:
    """Register the common deployment profile option."""

    parser.add_argument(
        "--profile",
        default=config.default_profile,
        help=f"Deployment profile name (default: {config.default_profile})",
    )


def add_serial_wait_arg(parser: argparse.ArgumentParser) -> None:
    """Register the serial wait option used by sync and post-flash flows."""

    parser.add_argument(
        "--serial-wait",
        type=float,
        default=DEFAULT_SERIAL_WAIT,
        help="Seconds to wait for serial port access",
    )


def add_db_arg(parser: argparse.ArgumentParser) -> None:
    """Register the common log database path option."""

    default_path = default_db_path()
    parser.add_argument(
        "--db-path",
        default=str(default_path),
        help=f"SQLite log database path (default: {default_path})",
    )


def build_parser(config: SwitcherConfig) -> argparse.ArgumentParser:
    """Construct and return the full CLI argument parser."""

    default_port = config.host.port
    default_mount_base = config.host.mount_base
    default_py_uf2 = config.host.micropython_uf2

    parser = argparse.ArgumentParser(description="Pico firmware switcher CLI (Linux)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_cmd = subparsers.add_parser("detect", help="Detect current Pico firmware mode")
    add_config_arg(detect_cmd)
    detect_cmd.add_argument("--port", default=default_port, help=f"{SERIAL_PORT_HELP} (default: {default_port})")
    detect_cmd.add_argument("--timeout", type=float, default=DEFAULT_DETECT_TIMEOUT)
    add_db_arg(detect_cmd)
    detect_cmd.add_argument("--verbose", action="store_true")

    flash_cmd = subparsers.add_parser("flash", help="Flash a UF2 while Pico is in BOOTSEL mode")
    add_config_arg(flash_cmd)
    flash_cmd.add_argument("uf2", help="Path to UF2 file")
    flash_cmd.add_argument("--mount-base", default=default_mount_base)
    flash_cmd.add_argument("--bootsel-timeout", type=float, default=DEFAULT_BOOTSEL_TIMEOUT)
    add_db_arg(flash_cmd)
    flash_cmd.add_argument("--verbose", action="store_true")

    to_py_cmd = subparsers.add_parser("to-py", help="Switch Pico to MicroPython UF2")
    add_config_arg(to_py_cmd)
    add_common_switch_args(to_py_cmd, default_port=default_port, default_mount_base=default_mount_base)
    add_profile_arg(to_py_cmd, config)
    to_py_cmd.add_argument("--uf2", default=str(default_py_uf2), help="MicroPython UF2 path")
    to_py_cmd.add_argument(
        "--install-helpers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=argparse.SUPPRESS,
    )

    sync_py_cmd = subparsers.add_parser(
        "sync-py",
        help="Sync switcher-owned MicroPython files and the selected client app",
    )
    add_config_arg(sync_py_cmd)
    sync_py_cmd.add_argument("--port", default=default_port, help=f"{SERIAL_PORT_HELP} (default: {default_port})")
    add_serial_wait_arg(sync_py_cmd)
    add_profile_arg(sync_py_cmd, config)
    add_db_arg(sync_py_cmd)
    sync_py_cmd.add_argument("--verbose", action="store_true")

    build_cpp_cmd = subparsers.add_parser(
        "build-cpp",
        help="Build the selected managed C++ profile into its configured UF2",
    )
    add_config_arg(build_cpp_cmd)
    add_profile_arg(build_cpp_cmd, config)
    add_db_arg(build_cpp_cmd)
    build_cpp_cmd.add_argument("--verbose", action="store_true")

    to_cpp_cmd = subparsers.add_parser("to-cpp", help="Switch Pico to C++ UF2")
    add_config_arg(to_cpp_cmd)
    add_common_switch_args(to_cpp_cmd, default_port=default_port, default_mount_base=default_mount_base)
    add_profile_arg(to_cpp_cmd, config)
    to_cpp_cmd.add_argument(
        "--uf2",
        help="C++ UF2 override; defaults to the selected profile output_uf2",
    )
    to_cpp_cmd.add_argument(
        "--build",
        action="store_true",
        help="Build the selected managed C++ profile before switching",
    )

    install_cmd = subparsers.add_parser(
        "install-py-files",
        help="Legacy alias for sync-py",
    )
    add_config_arg(install_cmd)
    install_cmd.add_argument("--port", default=default_port, help=f"{SERIAL_PORT_HELP} (default: {default_port})")
    add_serial_wait_arg(install_cmd)
    add_profile_arg(install_cmd, config)
    add_db_arg(install_cmd)
    install_cmd.add_argument("--verbose", action="store_true")

    log_state_cmd = subparsers.add_parser(
        "log-state",
        help="Detect the current state and append a snapshot row to the SQLite log",
    )
    add_config_arg(log_state_cmd)
    log_state_cmd.add_argument("--port", default=default_port, help=f"{SERIAL_PORT_HELP} (default: {default_port})")
    log_state_cmd.add_argument("--timeout", type=float, default=DEFAULT_DETECT_TIMEOUT)
    log_state_cmd.add_argument(
        "--source",
        default=DEFAULT_SNAPSHOT_SOURCE,
        help=f"Snapshot source label stored in the database (default: {DEFAULT_SNAPSHOT_SOURCE})",
    )
    add_db_arg(log_state_cmd)
    log_state_cmd.add_argument("--verbose", action="store_true")

    history_cmd = subparsers.add_parser("history", help="Show recent event and snapshot rows")
    history_cmd.add_argument(
        "--kind",
        default="all",
        choices=["all", "events", "snapshots"],
        help="Which rows to print (default: all)",
    )
    history_cmd.add_argument("--limit", type=int, help="Optional row limit per section")
    history_cmd.add_argument(
        "--full-details",
        action="store_true",
        help="Print raw details JSON instead of the compact summary view",
    )
    add_db_arg(history_cmd)

    backup_cmd = subparsers.add_parser(
        "backup-db",
        help="Create a consistent SQLite backup and send it to the configured remote host",
    )
    backup_cmd.add_argument(
        "--config",
        default=str(default_backup_config_path()),
        help=f"Backup config path (default: {default_backup_config_path()})",
    )
    add_db_arg(backup_cmd)
    backup_cmd.add_argument("--verbose", action="store_true")

    timer_cmd = subparsers.add_parser(
        "install-state-timer",
        help="Write systemd user units that record the current state every minute",
    )
    add_config_arg(timer_cmd)
    timer_cmd.add_argument("--port", default=default_port, help=f"{SERIAL_PORT_HELP} (default: {default_port})")
    timer_cmd.add_argument("--timeout", type=float, default=DEFAULT_DETECT_TIMEOUT)
    timer_cmd.add_argument(
        "--interval",
        default=DEFAULT_TIMER_INTERVAL,
        help=f"systemd timer interval for snapshots (default: {DEFAULT_TIMER_INTERVAL})",
    )
    timer_cmd.add_argument(
        "--unit-dir",
        default=str(DEFAULT_UNIT_DIR),
        help=f"Directory for user unit files (default: {DEFAULT_UNIT_DIR})",
    )
    timer_cmd.add_argument(
        "--service-name",
        default=DEFAULT_SERVICE_NAME,
        help=f"Base name for generated service and timer units (default: {DEFAULT_SERVICE_NAME})",
    )
    timer_cmd.add_argument(
        "--enable",
        action="store_true",
        help="Run `systemctl --user daemon-reload` and enable the timer immediately",
    )
    add_db_arg(timer_cmd)
    timer_cmd.add_argument("--verbose", action="store_true")

    return parser
