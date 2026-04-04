"""Argument parsing and command dispatch for the Pico switcher CLI.

This module defines the user-facing command surface, wires CLI flags into the
underlying service modules, and keeps top-level command behavior centralized so
the repo can evolve toward a thinner CLI over reusable core services.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import PROJECT_ROOT
from .pico_backup import (
    BackupTransferError,
    backup_database,
    default_backup_config_path,
    load_backup_config,
)
from .pico_device import (
    DEFAULT_MOUNT_BASE,
    DEFAULT_PORT,
    SERIAL_PORT_HELP,
    copy_uf2,
    wait_for_bootsel_mount,
)
from .pico_log import (
    DEFAULT_SNAPSHOT_SOURCE,
    EventRecorder,
    PicoLogStore,
    create_event_recorder,
    default_db_path,
)
from .pico_mpremote import DEFAULT_HELPER_FILES, install_micropython_helpers
from .pico_profiles import (
    CONFIG_FILE_NAME,
    SwitcherConfig,
    discover_config_path,
    load_switcher_config,
    require_profile_target,
    resolve_profile,
)
from .pico_switch import (
    DEFAULT_BOOTSEL_TIMEOUT,
    DEFAULT_DETECT_TIMEOUT,
    DEFAULT_INSTALL_HELPERS,
    DEFAULT_MODE,
    DEFAULT_SERIAL_WAIT,
    MIN_POST_SWITCH_DETECT_TIMEOUT,
    detect_mode,
    detect_mode_safe,
    switch_firmware,
)
from .pico_systemd import (
    DEFAULT_SERVICE_NAME,
    DEFAULT_TIMER_INTERVAL,
    DEFAULT_UNIT_DIR,
    enable_state_timer,
    install_state_timer,
)


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
    default_cpp_uf2 = config.host.cpp_uf2

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
    to_py_cmd.add_argument(
        "--profile",
        default=config.default_profile,
        help=f"Deployment profile name (default: {config.default_profile})",
    )
    to_py_cmd.add_argument("--uf2", default=str(default_py_uf2), help="MicroPython UF2 path")
    to_py_cmd.add_argument(
        "--install-helpers",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_INSTALL_HELPERS,
        help="Install py/boot.py and py/bootloader_trigger.py after flashing",
    )

    to_cpp_cmd = subparsers.add_parser("to-cpp", help="Switch Pico to C++ UF2")
    add_config_arg(to_cpp_cmd)
    add_common_switch_args(to_cpp_cmd, default_port=default_port, default_mount_base=default_mount_base)
    to_cpp_cmd.add_argument(
        "--profile",
        default=config.default_profile,
        help=f"Deployment profile name (default: {config.default_profile})",
    )
    to_cpp_cmd.add_argument("--uf2", default=str(default_cpp_uf2), help="C++ UF2 path")

    install_cmd = subparsers.add_parser(
        "install-py-files",
        help="Copy py/boot.py and py/bootloader_trigger.py to a MicroPython Pico",
    )
    add_config_arg(install_cmd)
    install_cmd.add_argument("--port", default=default_port, help=f"{SERIAL_PORT_HELP} (default: {default_port})")
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


def main() -> int:
    """Run the firmware switcher CLI and return a process exit code."""

    argv = sys.argv[1:]
    explicit_config_path = _extract_switcher_config_value(argv)
    switcher_config = load_switcher_config(
        discover_config_path(explicit_path=explicit_config_path),
    )
    parser = build_parser(switcher_config)
    args = parser.parse_args(argv)
    setattr(args, "switcher_config", switcher_config)
    recorder: EventRecorder | None = None

    try:
        if args.command == "history":
            return _run_history(args)

        recorder = _build_recorder(args)

        if args.command == "detect":
            return _run_detect(args, recorder)
        if args.command == "flash":
            return _run_flash(args, recorder)
        if args.command == "to-py":
            flashed = _run_switch(args=args, target="py", install_helpers=args.install_helpers, recorder=recorder)
            _print_switch_result(target="py", flashed=flashed)
            detect_timeout = max(args.detect_timeout, MIN_POST_SWITCH_DETECT_TIMEOUT)
            mode = detect_mode_safe(
                port=args.port,
                timeout=detect_timeout,
                verbose=args.verbose,
                recorder=recorder,
                reason="post_switch",
            )
            recorder.snapshot(
                mode=mode,
                port=args.port,
                source="post_switch",
                message="Recorded post-switch state snapshot",
                details={"target_mode": "py"},
            )
            print(f"detect: {mode or 'unknown'}")
            return 0
        if args.command == "to-cpp":
            flashed = _run_switch(args=args, target="cpp", install_helpers=False, recorder=recorder)
            _print_switch_result(target="cpp", flashed=flashed)
            return 0
        if args.command == "install-py-files":
            return _run_install_helpers(args, recorder)
        if args.command == "log-state":
            return _run_log_state(args, recorder)
        if args.command == "backup-db":
            return _run_backup_db(args, recorder)
        if args.command == "install-state-timer":
            return _run_install_state_timer(args, recorder)

        parser.error(f"Unknown command: {args.command}")
        return 2
    except Exception as exc:  # pragma: no cover - command line error path
        if recorder is not None:
            recorder.event(
                "command_failed",
                status="error",
                port=getattr(args, "port", None),
                message=str(exc),
                details={"command": args.command},
            )
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if recorder is not None:
            recorder.close()


def _build_recorder(args: argparse.Namespace) -> EventRecorder:
    """Create an event recorder for a CLI command."""

    return create_event_recorder(
        source=args.command,
        db_path=_expand_path(args.db_path),
        verbose=getattr(args, "verbose", False),
    )


def _run_detect(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle the `detect` command."""

    mode = detect_mode(
        port=args.port,
        timeout=args.timeout,
        verbose=args.verbose,
        recorder=recorder,
        reason="cli_detect",
    )
    if mode:
        print(mode)
        return 0
    print("unknown")
    return 1


def _run_flash(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle manual UF2 flashing while BOOTSEL mode is already active."""

    uf2_path = _expand_path(args.uf2)
    mountpoint: Path | None = None
    recorder.event(
        "flash_requested",
        message="Manual UF2 flash requested",
        details={
            "uf2_path": str(uf2_path),
            "mount_base": args.mount_base,
        },
    )
    try:
        mountpoint = wait_for_bootsel_mount(
            timeout=args.bootsel_timeout,
            mount_base=args.mount_base,
            verbose=args.verbose,
        )
        copy_uf2(uf2_path=uf2_path, mountpoint=mountpoint, verbose=args.verbose)
    except Exception as exc:
        recorder.event(
            "uf2_flash",
            status="error",
            mountpoint=None if mountpoint is None else str(mountpoint),
            message=str(exc),
            details={"uf2_path": str(uf2_path)},
        )
        raise
    recorder.event(
        "uf2_flash",
        mountpoint=str(mountpoint),
        message=f"Flashed {uf2_path.name}",
        details={"uf2_path": str(uf2_path)},
    )
    return 0


def _run_switch(
    args: argparse.Namespace,
    target: str,
    install_helpers: bool,
    recorder: EventRecorder,
) -> bool:
    """Invoke the common switch workflow used by `to-py` and `to-cpp`."""

    profile = resolve_profile(args.switcher_config, getattr(args, "profile", None))
    require_profile_target(profile, target)

    return switch_firmware(
        target=target,
        port=args.port,
        mode=args.mode,
        uf2_path=_expand_path(args.uf2),
        mount_base=args.mount_base,
        detect_timeout=args.detect_timeout,
        bootsel_timeout=args.bootsel_timeout,
        install_helpers=install_helpers,
        helper_files=None,
        serial_wait=args.serial_wait,
        force_flash=args.force_flash,
        verbose=args.verbose,
        recorder=recorder,
    )


def _run_install_helpers(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle the explicit helper file install command."""

    recorder.event(
        "helpers_install_requested",
        port=args.port,
        message="MicroPython helper file install requested",
        details={"helper_files": [str(file_path) for file_path in DEFAULT_HELPER_FILES]},
    )
    try:
        install_micropython_helpers(
            port=args.port,
            verbose=args.verbose,
        )
    except Exception as exc:
        recorder.event(
            "helpers_install",
            status="error",
            port=args.port,
            message=str(exc),
            details={"helper_files": [str(file_path) for file_path in DEFAULT_HELPER_FILES]},
        )
        raise
    recorder.event(
        "helpers_install",
        port=args.port,
        message="Installed MicroPython helper files",
        details={"helper_files": [str(file_path) for file_path in DEFAULT_HELPER_FILES]},
    )
    return 0


def _run_log_state(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle the explicit state snapshot command."""

    error_message: str | None = None
    try:
        mode = detect_mode(
            port=args.port,
            timeout=args.timeout,
            verbose=args.verbose,
            recorder=recorder,
            reason=f"snapshot:{args.source}",
        )
    except Exception as exc:
        mode = None
        error_message = str(exc)
        if args.verbose:
            print(f"State snapshot detect failed: {exc}")
        recorder.event(
            "detect_mode",
            status="error",
            port=args.port,
            message=error_message,
            details={"reason": f"snapshot:{args.source}"},
        )

    recorder.snapshot(
        mode=mode,
        port=args.port,
        source=args.source,
        message="Recorded state snapshot" if error_message is None else error_message,
        details={
            "status": "ok" if error_message is None else "error",
            "requested_port": args.port,
        },
    )
    print(mode or "unknown")
    return 0


def _run_history(args: argparse.Namespace) -> int:
    """Handle the history reporting command."""

    store = PicoLogStore(_expand_path(args.db_path))
    try:
        if args.kind in {"all", "events"}:
            _print_history_section(
                "Events",
                store.fetch_events(limit=args.limit),
                event_rows=True,
                full_details=args.full_details,
            )
        if args.kind in {"all", "snapshots"}:
            if args.kind == "all":
                print()
            _print_history_section(
                "Snapshots",
                store.fetch_snapshots(limit=args.limit),
                event_rows=False,
                full_details=args.full_details,
            )
    finally:
        store.close()
    return 0


def _run_backup_db(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle the manual database backup command."""

    config_path = _expand_path(args.config)
    db_path = _expand_path(args.db_path)
    config = load_backup_config(config_path)
    recorder.event(
        "backup_requested",
        message="SQLite backup requested",
        details={
            "config_path": str(config_path),
            "db_path": str(db_path),
            "remote_host": config.remote.host,
            "remote_path": config.remote.path,
        },
    )

    try:
        result = backup_database(
            db_path=db_path,
            config=config,
            verbose=args.verbose,
        )
    except BackupTransferError as exc:
        recorder.event(
            "backup_transfer",
            status="error",
            message=str(exc),
            details={
                "config_path": str(config_path),
                "db_path": str(db_path),
                "staged_path": str(exc.staged_path),
                "remote_uri": exc.remote_uri,
            },
        )
        raise
    except Exception as exc:
        recorder.event(
            "backup_creation",
            status="error",
            message=str(exc),
            details={
                "config_path": str(config_path),
                "db_path": str(db_path),
            },
        )
        raise

    recorder.event(
        "backup_transfer",
        message="Transferred SQLite backup to remote host",
        details={
            "config_path": str(config_path),
            "db_path": str(db_path),
            "file_name": result.file_name,
            "remote_uri": result.remote_uri,
            "size_bytes": result.size_bytes,
            "compressed": result.compressed,
        },
    )
    print(f"backup: {result.file_name}")
    print(f"remote: {result.remote_uri}")
    print(f"size: {result.size_bytes}")
    return 0


def _run_install_state_timer(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle generation of systemd user units for periodic snapshots."""

    db_path = _expand_path(args.db_path)
    units = install_state_timer(
        db_path=db_path,
        port=args.port,
        timeout=args.timeout,
        unit_dir=_expand_path(args.unit_dir),
        service_name=args.service_name,
        interval=args.interval,
    )
    recorder.event(
        "state_timer_installed",
        port=args.port,
        message="Installed systemd user units for periodic state snapshots",
        details={
            "interval": args.interval,
            "service_name": args.service_name,
            "unit_dir": str(_expand_path(args.unit_dir)),
            "db_path": str(db_path),
        },
    )

    if args.enable:
        try:
            enable_state_timer(args.service_name)
        except Exception as exc:
            recorder.event(
                "state_timer_enabled",
                status="error",
                message=str(exc),
                details={"service_name": args.service_name},
            )
            raise
        recorder.event(
            "state_timer_enabled",
            message="Enabled periodic state snapshot timer",
            details={"service_name": args.service_name},
        )

    print(f"service: {units.service_path}")
    print(f"timer: {units.timer_path}")
    if args.enable:
        print(f"enabled: {args.service_name}.timer")
    else:
        print("next: systemctl --user daemon-reload")
        print(f"next: systemctl --user enable --now {args.service_name}.timer")
    return 0


def _print_history_section(
    title: str,
    rows: list[dict[str, object]],
    event_rows: bool,
    *,
    full_details: bool = False,
) -> None:
    """Print one history section in a compact single-line-per-row format."""

    print(title)
    if not rows:
        print("  none")
        return

    for row in rows:
        details = row.get("details")
        detail_parts = _format_history_details(
            details=details,
            event_type=str(row.get("event_type")) if event_rows else None,
            full_details=full_details,
        )
        parts = [_format_history_timestamp(str(row["created_at"]))]
        if event_rows:
            parts.extend(
                [
                    str(row["status"]),
                    str(row["event_type"]),
                    f"source={row['source']}",
                ]
            )
            if row.get("mode"):
                parts.append(f"mode={row['mode']}")
            if row.get("target_mode"):
                parts.append(f"target={row['target_mode']}")
            if row.get("mountpoint"):
                parts.append(f"mount={row['mountpoint']}")
        else:
            parts.extend(
                [
                    "snapshot",
                    f"source={row['source']}",
                    f"mode={row.get('mode') or 'unknown'}",
                ]
            )
        if row.get("port"):
            parts.append(f"port={row['port']}")
        if _should_include_history_message(row=row, detail_parts=detail_parts, full_details=full_details):
            parts.append(f"message={row['message']}")
        parts.extend(detail_parts)
        print("  " + " | ".join(parts))


_DETAIL_LABELS = {
    "command": "cmd",
    "config_path": "cfg",
    "db_path": "db",
    "file_name": "file",
    "force_flash": "force",
    "helper_files": "files",
    "interval": "every",
    "mount_base": "base",
    "reason": "reason",
    "remote_host": "host",
    "remote_path": "dest",
    "remote_uri": "remote",
    "requested_port": "req",
    "service_name": "service",
    "size_bytes": "size",
    "staged_path": "staged",
    "status": "status",
    "uf2_path": "uf2",
    "unit_dir": "units",
}

_DETAIL_PRIORITY = {
    "file_name": 0,
    "config_path": 1,
    "db_path": 2,
    "remote_host": 3,
    "remote_path": 4,
    "remote_uri": 5,
    "staged_path": 6,
    "service_name": 7,
    "interval": 8,
    "uf2_path": 9,
    "helper_files": 10,
    "reason": 11,
    "status": 12,
    "requested_port": 13,
    "force_flash": 14,
    "command": 15,
    "unit_dir": 16,
    "mount_base": 17,
}


def _format_history_details(
    *,
    details: object,
    event_type: str | None,
    full_details: bool,
) -> list[str]:
    """Return compact or raw detail fragments for one history row."""

    if not details:
        return []
    if full_details:
        return [f"details={json.dumps(details, sort_keys=True)}"]
    if not isinstance(details, dict):
        return [f"details={_truncate_text(str(details), 120)}"]

    rendered_items: list[str] = []
    for key, value in sorted(details.items(), key=lambda item: (_DETAIL_PRIORITY.get(item[0], 99), item[0])):
        rendered = _render_history_detail_item(key, value)
        if rendered:
            rendered_items.append(rendered)

    if not rendered_items:
        return []

    preferred_limit = 4 if event_type != "backup_transfer" else 5
    if len(rendered_items) <= preferred_limit:
        return rendered_items
    omitted_count = len(rendered_items) - preferred_limit
    return rendered_items[:preferred_limit] + [f"+{omitted_count} more"]


def _render_history_detail_item(key: str, value: object) -> str | None:
    """Render one detail entry in a compact human-readable form."""

    if value is None:
        return None
    label = _DETAIL_LABELS.get(key, key)
    rendered_value = _render_history_detail_value(key, value)
    if rendered_value == "":
        return None
    return f"{label}={rendered_value}"


def _render_history_detail_value(key: str, value: object) -> str:
    """Render one detail value in a compact human-readable form."""

    if key == "remote_uri" and isinstance(value, str):
        return _short_remote_uri(value)
    if key in {"config_path", "db_path", "staged_path", "uf2_path", "unit_dir", "mount_base"} and isinstance(value, str):
        return _short_path(value)
    if key == "remote_path" and isinstance(value, str):
        return _short_path(value, tail_segments=1)
    if key == "helper_files" and isinstance(value, list):
        return _render_history_list(value, treat_as_path=True)
    if key == "size_bytes" and isinstance(value, int):
        return f"{value}B"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return _render_history_list(value)
    return _truncate_text(str(value), 80)


def _render_history_list(values: list[Any], *, treat_as_path: bool = False) -> str:
    """Render a list value compactly for history output."""

    items: list[str] = []
    for value in values:
        text = str(value)
        items.append(_short_path(text) if treat_as_path else _truncate_text(text, 32))

    if len(items) <= 2:
        return ",".join(items)
    return ",".join(items[:2]) + f",+{len(items) - 2}"


def _short_remote_uri(remote_uri: str) -> str:
    """Compact a remote URI to host plus a short tail path."""

    host, separator, path = remote_uri.partition(":")
    if not separator:
        return _truncate_text(remote_uri, 80)
    return f"{host}:{_short_path(path, tail_segments=2)}"


def _short_path(path_value: str, *, tail_segments: int = 1) -> str:
    """Compact a filesystem path for terminal display."""

    path = Path(path_value).expanduser()
    if path.is_absolute():
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            parts = list(path.parts)
            if parts and parts[0] == path.anchor:
                parts = parts[1:]
            if len(parts) >= tail_segments:
                return "/".join(parts[-tail_segments:])
            if path.name:
                return path.name
    return _truncate_text(path_value, 80)


def _format_history_timestamp(value: str) -> str:
    """Normalize history timestamps for compact output."""

    return value.replace("+00:00", "Z")


def _truncate_text(value: str, limit: int) -> str:
    """Trim long strings so single-line history stays readable."""

    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _should_include_history_message(
    *,
    row: dict[str, object],
    detail_parts: list[str],
    full_details: bool,
) -> bool:
    """Decide whether to print the free-form message for one row."""

    if not row.get("message"):
        return False
    if full_details:
        return True
    return row.get("status") == "error" or not detail_parts


def _print_switch_result(target: str, flashed: bool) -> None:
    """Print the post-switch status line shown to CLI users."""

    if target == "py":
        print("Switched to MicroPython UF2." if flashed else "Already in MicroPython mode; skipped UF2 flash.")
        return
    print("Switched to C++ UF2." if flashed else "Already in C++ mode; skipped UF2 flash.")


def _expand_path(path_value: str) -> Path:
    """Expand a user-provided path string to a filesystem path."""

    return Path(path_value).expanduser()


def _extract_cli_option_value(argv: list[str], option_name: str) -> str | None:
    """Extract one option value from raw argv without fully parsing the CLI."""

    for index, item in enumerate(argv):
        if item == option_name:
            if index + 1 < len(argv):
                return argv[index + 1]
            return None
        if item.startswith(f"{option_name}="):
            return item.split("=", 1)[1]
    return None


def _extract_switcher_config_value(argv: list[str]) -> str | None:
    """Extract `--config` only for commands that use it as switcher config."""

    command = _extract_subcommand(argv)
    if command not in {
        "detect",
        "flash",
        "to-py",
        "to-cpp",
        "install-py-files",
        "log-state",
        "install-state-timer",
    }:
        return None
    return _extract_cli_option_value(argv, "--config")


def _extract_subcommand(argv: list[str]) -> str | None:
    """Return the CLI subcommand from raw argv."""

    for item in argv:
        if not item.startswith("-"):
            return item
    return None
