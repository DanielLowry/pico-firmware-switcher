"""Command handlers for side-effectful CLI operations.

These functions are the execution layer for individual CLI commands. They keep
argparse-specific behavior at the edges while delegating the real work to the
existing service modules.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..pico_backup import BackupTransferError, backup_database, load_backup_config
from ..pico_cpp import build_managed_cpp_plan, build_managed_cpp_profile
from ..pico_cpp_contract import CPP_BOOTSEL_COMMAND, CPP_CLIENT_ENTRY_SYMBOL
from ..pico_device import copy_uf2, wait_for_bootsel_mount, wait_for_serial_port
from ..pico_log import EventRecorder
from ..pico_micropython import (
    MANAGED_BOOT_FILE_NAME,
    MANAGED_MAIN_FILE_NAME,
    MANAGED_METADATA_FILE_NAME,
    build_managed_python_sync_plan,
    sync_managed_python_profile,
)
from ..pico_switch import detect_mode, switch_firmware
from ..pico_systemd import enable_state_timer, install_state_timer
from .utils import expand_path, resolve_profile_for_target, resolve_switch_uf2_path


def run_detect(args: argparse.Namespace, recorder: EventRecorder) -> int:
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


def run_flash(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle manual UF2 flashing while BOOTSEL mode is already active."""

    uf2_path = expand_path(args.uf2)
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


def run_switch(
    args: argparse.Namespace,
    *,
    target: str,
    install_helpers: bool,
    recorder: EventRecorder,
) -> bool:
    """Invoke the common switch workflow used by `to-py` and `to-cpp`."""

    profile = resolve_profile_for_target(args, target)
    uf2_path = resolve_switch_uf2_path(args=args, target=target, profile=profile)

    return switch_firmware(
        target=target,
        port=args.port,
        mode=args.mode,
        uf2_path=uf2_path,
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


def run_sync_py(args: argparse.Namespace, recorder: EventRecorder, *, reason: str) -> None:
    """Sync managed MicroPython runtime files and the selected client app."""

    profile = resolve_profile_for_target(args, "py")
    assert profile.python is not None  # covered by resolve_profile_for_target
    plan = build_managed_python_sync_plan(profile.name, profile.python)

    recorder.event(
        "py_sync_requested",
        port=args.port,
        message="Managed MicroPython sync requested",
        details={
            "reason": reason,
            "profile": profile.name,
            "source_dir": str(plan.source_dir),
            "entry_module": plan.entry_module,
            "entry_function": plan.entry_function,
        },
    )
    try:
        resolved_port = wait_for_serial_port(port=args.port, timeout=args.serial_wait, verbose=args.verbose)
        sync_managed_python_profile(
            port=resolved_port,
            plan=plan,
            verbose=args.verbose,
        )
    except Exception as exc:
        recorder.event(
            "py_sync",
            status="error",
            port=args.port,
            message=str(exc),
            details={
                "reason": reason,
                "profile": profile.name,
                "source_dir": str(plan.source_dir),
                "entry_module": plan.entry_module,
                "entry_function": plan.entry_function,
                "runtime_files": [
                    MANAGED_BOOT_FILE_NAME,
                    MANAGED_MAIN_FILE_NAME,
                    MANAGED_METADATA_FILE_NAME,
                ],
            },
        )
        raise
    recorder.event(
        "py_sync",
        port=resolved_port,
        message="Synced managed MicroPython files",
        details={
            "reason": reason,
            "profile": profile.name,
            "source_dir": str(plan.source_dir),
            "entry_module": plan.entry_module,
            "entry_function": plan.entry_function,
            "runtime_files": [
                MANAGED_BOOT_FILE_NAME,
                MANAGED_MAIN_FILE_NAME,
                MANAGED_METADATA_FILE_NAME,
            ],
        },
    )


def run_build_cpp(args: argparse.Namespace, recorder: EventRecorder, *, reason: str) -> Path:
    """Build the selected managed C++ profile and return the resulting UF2."""

    if getattr(args, "uf2", None):
        raise RuntimeError("`--uf2` cannot be combined with managed C++ build; use profile.cpp.output_uf2 instead")

    profile = resolve_profile_for_target(args, "cpp")
    assert profile.cpp is not None  # covered by resolve_profile_for_target
    plan = build_managed_cpp_plan(profile.name, profile.cpp)

    recorder.event(
        "cpp_build_requested",
        message="Managed C++ build requested",
        details={
            "reason": reason,
            "profile": profile.name,
            "source_dir": str(plan.source_dir),
            "sources": [str(source_path) for source_path in plan.sources],
            "build_dir": str(plan.build_dir),
            "uf2_path": str(plan.output_uf2),
            "entry_symbol": CPP_CLIENT_ENTRY_SYMBOL,
            "bootsel_command": CPP_BOOTSEL_COMMAND,
        },
    )
    try:
        output_uf2 = build_managed_cpp_profile(plan, verbose=args.verbose)
    except Exception as exc:
        recorder.event(
            "cpp_build",
            status="error",
            message=str(exc),
            details={
                "reason": reason,
                "profile": profile.name,
                "source_dir": str(plan.source_dir),
                "sources": [str(source_path) for source_path in plan.sources],
                "build_dir": str(plan.build_dir),
                "uf2_path": str(plan.output_uf2),
                "entry_symbol": CPP_CLIENT_ENTRY_SYMBOL,
                "bootsel_command": CPP_BOOTSEL_COMMAND,
            },
        )
        raise

    recorder.event(
        "cpp_build",
        message="Built managed C++ profile",
        details={
            "reason": reason,
            "profile": profile.name,
            "source_dir": str(plan.source_dir),
            "sources": [str(source_path) for source_path in plan.sources],
            "build_dir": str(plan.build_dir),
            "uf2_path": str(output_uf2),
            "entry_symbol": CPP_CLIENT_ENTRY_SYMBOL,
            "bootsel_command": CPP_BOOTSEL_COMMAND,
        },
    )
    return output_uf2


def run_log_state(args: argparse.Namespace, recorder: EventRecorder) -> int:
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


def run_backup_db(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle the manual database backup command."""

    config_path = expand_path(args.config)
    db_path = expand_path(args.db_path)
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


def run_install_state_timer(args: argparse.Namespace, recorder: EventRecorder) -> int:
    """Handle generation of systemd user units for periodic snapshots."""

    db_path = expand_path(args.db_path)
    units = install_state_timer(
        db_path=db_path,
        port=args.port,
        timeout=args.timeout,
        unit_dir=expand_path(args.unit_dir),
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
            "unit_dir": str(expand_path(args.unit_dir)),
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
