"""Argument parsing and command dispatch for the Pico switcher CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pico_device import (
    DEFAULT_MOUNT_BASE,
    DEFAULT_PORT,
    SERIAL_PORT_HELP,
    copy_uf2,
    wait_for_bootsel_mount,
)
from .pico_log import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_SNAPSHOT_SOURCE,
    EventRecorder,
    PicoLogStore,
    create_event_recorder,
    default_db_path,
)
from .pico_mpremote import DEFAULT_HELPER_FILES, install_micropython_helpers
from .pico_switch import (
    DEFAULT_BOOTSEL_TIMEOUT,
    DEFAULT_CPP_UF2,
    DEFAULT_DETECT_TIMEOUT,
    DEFAULT_INSTALL_HELPERS,
    DEFAULT_MODE,
    DEFAULT_PY_UF2,
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


def add_common_switch_args(parser: argparse.ArgumentParser) -> None:
    """Register CLI arguments shared by `to-py` and `to-cpp`."""

    parser.add_argument("--port", default=DEFAULT_PORT, help=f"{SERIAL_PORT_HELP} (default: {DEFAULT_PORT})")
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        choices=["auto", "py", "cpp", "bootsel"],
        help=f"Current firmware mode override (default: {DEFAULT_MODE})",
    )
    parser.add_argument(
        "--mount-base",
        default=DEFAULT_MOUNT_BASE,
        help=f"Mount point to use when RPI-RP2 is not auto-mounted (default: {DEFAULT_MOUNT_BASE})",
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


def add_db_arg(parser: argparse.ArgumentParser) -> None:
    """Register the common log database path option."""

    default_path = default_db_path()
    parser.add_argument(
        "--db-path",
        default=str(default_path),
        help=f"SQLite log database path (default: {default_path})",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the full CLI argument parser."""

    parser = argparse.ArgumentParser(description="Pico firmware switcher CLI (Linux)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_cmd = subparsers.add_parser("detect", help="Detect current Pico firmware mode")
    detect_cmd.add_argument("--port", default=DEFAULT_PORT, help=f"{SERIAL_PORT_HELP} (default: {DEFAULT_PORT})")
    detect_cmd.add_argument("--timeout", type=float, default=DEFAULT_DETECT_TIMEOUT)
    add_db_arg(detect_cmd)
    detect_cmd.add_argument("--verbose", action="store_true")

    flash_cmd = subparsers.add_parser("flash", help="Flash a UF2 while Pico is in BOOTSEL mode")
    flash_cmd.add_argument("uf2", help="Path to UF2 file")
    flash_cmd.add_argument("--mount-base", default=DEFAULT_MOUNT_BASE)
    flash_cmd.add_argument("--bootsel-timeout", type=float, default=DEFAULT_BOOTSEL_TIMEOUT)
    add_db_arg(flash_cmd)
    flash_cmd.add_argument("--verbose", action="store_true")

    to_py_cmd = subparsers.add_parser("to-py", help="Switch Pico to MicroPython UF2")
    add_common_switch_args(to_py_cmd)
    to_py_cmd.add_argument("--uf2", default=str(DEFAULT_PY_UF2), help="MicroPython UF2 path")
    to_py_cmd.add_argument(
        "--install-helpers",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_INSTALL_HELPERS,
        help="Install py/boot.py and py/bootloader_trigger.py after flashing",
    )

    to_cpp_cmd = subparsers.add_parser("to-cpp", help="Switch Pico to C++ UF2")
    add_common_switch_args(to_cpp_cmd)
    to_cpp_cmd.add_argument("--uf2", default=str(DEFAULT_CPP_UF2), help="C++ UF2 path")

    install_cmd = subparsers.add_parser(
        "install-py-files",
        help="Copy py/boot.py and py/bootloader_trigger.py to a MicroPython Pico",
    )
    install_cmd.add_argument("--port", default=DEFAULT_PORT, help=f"{SERIAL_PORT_HELP} (default: {DEFAULT_PORT})")
    add_db_arg(install_cmd)
    install_cmd.add_argument("--verbose", action="store_true")

    log_state_cmd = subparsers.add_parser(
        "log-state",
        help="Detect the current state and append a snapshot row to the SQLite log",
    )
    log_state_cmd.add_argument("--port", default=DEFAULT_PORT, help=f"{SERIAL_PORT_HELP} (default: {DEFAULT_PORT})")
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
    history_cmd.add_argument("--limit", type=int, default=DEFAULT_HISTORY_LIMIT, help="Rows to show per section")
    add_db_arg(history_cmd)

    timer_cmd = subparsers.add_parser(
        "install-state-timer",
        help="Write systemd user units that record the current state every 5 minutes",
    )
    timer_cmd.add_argument("--port", default=DEFAULT_PORT, help=f"{SERIAL_PORT_HELP} (default: {DEFAULT_PORT})")
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

    parser = build_parser()
    args = parser.parse_args()
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
            _print_history_section("Events", store.fetch_events(limit=args.limit), event_rows=True)
        if args.kind in {"all", "snapshots"}:
            if args.kind == "all":
                print()
            _print_history_section("Snapshots", store.fetch_snapshots(limit=args.limit), event_rows=False)
    finally:
        store.close()
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


def _print_history_section(title: str, rows: list[dict[str, object]], event_rows: bool) -> None:
    """Print one history section in a compact single-line-per-row format."""

    print(title)
    if not rows:
        print("  none")
        return

    for row in rows:
        details = row.get("details")
        parts = [str(row["created_at"])]
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
        if row.get("message"):
            parts.append(f"message={row['message']}")
        if details:
            parts.append(f"details={json.dumps(details, sort_keys=True)}")
        print("  " + " | ".join(parts))


def _print_switch_result(target: str, flashed: bool) -> None:
    """Print the post-switch status line shown to CLI users."""

    if target == "py":
        print("Switched to MicroPython UF2." if flashed else "Already in MicroPython mode; skipped UF2 flash.")
        return
    print("Switched to C++ UF2." if flashed else "Already in C++ mode; skipped UF2 flash.")


def _expand_path(path_value: str) -> Path:
    """Expand a user-provided path string to a filesystem path."""

    return Path(path_value).expanduser()
