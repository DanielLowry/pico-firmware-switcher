"""CLI bootstrap and command orchestration.

This module owns the top-level `argv` flow: discover config, build the parser,
dispatch commands, manage the recorder lifecycle, and keep the composite CLI
flows such as `to-py` and `to-cpp --build` readable.
"""

from __future__ import annotations

import argparse
import sys

from ..pico_log import EventRecorder, create_event_recorder
from ..pico_profiles import discover_config_path, load_switcher_config
from ..pico_switch import MIN_POST_SWITCH_DETECT_TIMEOUT, detect_mode_safe
from . import handlers, history
from .parser import build_parser
from .utils import (
    expand_path,
    extract_switcher_config_value,
    print_cpp_build_result,
    print_py_sync_result,
    print_switch_result,
)


def run_cli(argv: list[str] | None = None) -> int:
    """Run the firmware switcher CLI and return a process exit code."""

    resolved_argv = sys.argv[1:] if argv is None else argv
    explicit_config_path = extract_switcher_config_value(resolved_argv)
    switcher_config = load_switcher_config(
        discover_config_path(explicit_path=explicit_config_path),
    )
    parser = build_parser(switcher_config)
    args = parser.parse_args(resolved_argv)
    setattr(args, "switcher_config", switcher_config)
    recorder: EventRecorder | None = None

    try:
        if args.command == "history":
            return history.run_history(args)

        recorder = _build_recorder(args)

        if args.command == "detect":
            return handlers.run_detect(args, recorder)
        if args.command == "flash":
            return handlers.run_flash(args, recorder)
        if args.command == "to-py":
            flashed = handlers.run_switch(args=args, target="py", install_helpers=False, recorder=recorder)
            print_switch_result(target="py", flashed=flashed)
            handlers.run_sync_py(args, recorder, reason="post_switch")
            print_py_sync_result(args.profile)
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
        if args.command == "sync-py":
            handlers.run_sync_py(args, recorder, reason="cli_sync")
            print_py_sync_result(args.profile)
            return 0
        if args.command == "build-cpp":
            output_uf2 = handlers.run_build_cpp(args, recorder, reason="cli_build")
            print_cpp_build_result(args.profile, output_uf2)
            return 0
        if args.command == "to-cpp":
            built_uf2 = None
            if args.build:
                built_uf2 = handlers.run_build_cpp(args, recorder, reason="pre_switch")
            flashed = handlers.run_switch(args=args, target="cpp", install_helpers=False, recorder=recorder)
            if built_uf2 is not None:
                print_cpp_build_result(args.profile, built_uf2)
            print_switch_result(target="cpp", flashed=flashed)
            return 0
        if args.command == "install-py-files":
            handlers.run_sync_py(args, recorder, reason="legacy_install")
            print_py_sync_result(args.profile)
            return 0
        if args.command == "log-state":
            return handlers.run_log_state(args, recorder)
        if args.command == "backup-db":
            return handlers.run_backup_db(args, recorder)
        if args.command == "install-state-timer":
            return handlers.run_install_state_timer(args, recorder)

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
        db_path=expand_path(args.db_path),
        verbose=getattr(args, "verbose", False),
    )
