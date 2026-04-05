"""Refactor-safety tests for the split CLI package.

These tests verify that the `pico_cli.py` split preserved the observable CLI
shape while moving parser, handlers, history rendering, and bootstrap code into
smaller modules. They intentionally mock the execution layer so the tests stay
fast and focused on CLI structure.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

from pico_switcher import PROJECT_ROOT
from pico_switcher.cli.history import print_history_section
from pico_switcher.cli.parser import build_parser
from pico_switcher.cli.runner import run_cli
from pico_switcher.cli.utils import extract_switcher_config_value
from pico_switcher.pico_profiles import load_switcher_config
from pico_switcher.pico_switch import MIN_POST_SWITCH_DETECT_TIMEOUT


class CliUtilsTests(unittest.TestCase):
    def test_extract_switcher_config_value_reads_switch_commands_only(self) -> None:
        self.assertEqual(
            extract_switcher_config_value(["to-py", "--config", "switcher.toml"]),
            "switcher.toml",
        )
        self.assertIsNone(
            extract_switcher_config_value(["backup-db", "--config", "backup.toml"]),
        )


class CliParserTests(unittest.TestCase):
    def test_build_parser_exposes_expected_commands_and_flags(self) -> None:
        parser = build_parser(load_switcher_config(None))

        help_text = parser.format_help()
        self.assertIn("build-cpp", help_text)
        self.assertIn("sync-py", help_text)
        self.assertIn("to-cpp", help_text)

        build_args = parser.parse_args(["build-cpp", "--profile", "demo"])
        to_cpp_args = parser.parse_args(["to-cpp", "--profile", "demo", "--build"])

        self.assertEqual(build_args.command, "build-cpp")
        self.assertEqual(build_args.profile, "demo")
        self.assertEqual(to_cpp_args.command, "to-cpp")
        self.assertTrue(to_cpp_args.build)


class CliRunnerTests(unittest.TestCase):
    def test_run_cli_dispatches_history_without_creating_recorder(self) -> None:
        args = argparse.Namespace(
            command="history",
            db_path="/tmp/events.sqlite3",
            kind="all",
            limit=None,
            full_details=False,
        )
        parser = mock.Mock()
        parser.parse_args.return_value = args

        with mock.patch("pico_switcher.cli.runner.discover_config_path", return_value=None), mock.patch(
            "pico_switcher.cli.runner.load_switcher_config",
            return_value=load_switcher_config(None),
        ), mock.patch("pico_switcher.cli.runner.build_parser", return_value=parser), mock.patch(
            "pico_switcher.cli.runner.history.run_history",
            return_value=0,
        ) as history_mock, mock.patch("pico_switcher.cli.runner.create_event_recorder") as recorder_factory:
            result = run_cli(["history"])

        self.assertEqual(result, 0)
        history_mock.assert_called_once_with(args)
        recorder_factory.assert_not_called()

    def test_run_cli_dispatches_build_cpp_handler(self) -> None:
        args = argparse.Namespace(
            command="build-cpp",
            db_path="/tmp/events.sqlite3",
            verbose=False,
            profile="demo",
        )
        parser = mock.Mock()
        parser.parse_args.return_value = args
        recorder = mock.Mock()
        output_uf2 = Path("/tmp/demo.uf2")

        with mock.patch("pico_switcher.cli.runner.discover_config_path", return_value=None), mock.patch(
            "pico_switcher.cli.runner.load_switcher_config",
            return_value=load_switcher_config(None),
        ), mock.patch("pico_switcher.cli.runner.build_parser", return_value=parser), mock.patch(
            "pico_switcher.cli.runner.create_event_recorder",
            return_value=recorder,
        ), mock.patch("pico_switcher.cli.runner.handlers.run_build_cpp", return_value=output_uf2) as build_mock, mock.patch(
            "pico_switcher.cli.runner.print_cpp_build_result"
        ) as print_mock:
            result = run_cli(["build-cpp", "--profile", "demo"])

        self.assertEqual(result, 0)
        build_mock.assert_called_once_with(args, recorder, reason="cli_build")
        print_mock.assert_called_once_with("demo", output_uf2)
        recorder.close.assert_called_once()

    def test_run_cli_handles_composite_to_py_flow(self) -> None:
        args = argparse.Namespace(
            command="to-py",
            db_path="/tmp/events.sqlite3",
            verbose=False,
            profile="demo",
            port="/dev/ttyACM0",
            detect_timeout=0.1,
        )
        parser = mock.Mock()
        parser.parse_args.return_value = args
        recorder = mock.Mock()

        with mock.patch("pico_switcher.cli.runner.discover_config_path", return_value=None), mock.patch(
            "pico_switcher.cli.runner.load_switcher_config",
            return_value=load_switcher_config(None),
        ), mock.patch("pico_switcher.cli.runner.build_parser", return_value=parser), mock.patch(
            "pico_switcher.cli.runner.create_event_recorder",
            return_value=recorder,
        ), mock.patch("pico_switcher.cli.runner.handlers.run_switch", return_value=False) as switch_mock, mock.patch(
            "pico_switcher.cli.runner.handlers.run_sync_py"
        ) as sync_mock, mock.patch("pico_switcher.cli.runner.print_switch_result") as print_switch_mock, mock.patch(
            "pico_switcher.cli.runner.print_py_sync_result"
        ) as print_sync_mock, mock.patch(
            "pico_switcher.cli.runner.detect_mode_safe",
            return_value="py",
        ) as detect_mock:
            result = run_cli(["to-py", "--profile", "demo"])

        self.assertEqual(result, 0)
        switch_mock.assert_called_once_with(args=args, target="py", install_helpers=False, recorder=recorder)
        sync_mock.assert_called_once_with(args, recorder, reason="post_switch")
        print_switch_mock.assert_called_once_with(target="py", flashed=False)
        print_sync_mock.assert_called_once_with("demo")
        detect_mock.assert_called_once_with(
            port="/dev/ttyACM0",
            timeout=MIN_POST_SWITCH_DETECT_TIMEOUT,
            verbose=False,
            recorder=recorder,
            reason="post_switch",
        )
        recorder.snapshot.assert_called_once()
        recorder.close.assert_called_once()


class CliHistoryTests(unittest.TestCase):
    def test_snapshot_history_output_stays_compact(self) -> None:
        row = {
            "created_at": "2026-04-05T09:10:11+00:00",
            "source": "timer",
            "mode": "cpp",
            "port": "/dev/ttyACM0",
            "message": "Recorded snapshot",
            "details": {"status": "ok", "requested_port": "/dev/ttyACM0"},
        }

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_history_section("Snapshots", [row], event_rows=False)

        output = buffer.getvalue()
        self.assertIn("2026-04-05T09:10:11Z", output)
        self.assertIn("snapshot | source=timer | mode=cpp", output)
        self.assertIn("port=/dev/ttyACM0", output)
        self.assertNotIn("details={", output)


class CliLayoutTests(unittest.TestCase):
    def test_cli_modules_respect_line_limits(self) -> None:
        cli_root = PROJECT_ROOT / "pico_switcher" / "cli"
        file_limits = {PROJECT_ROOT / "pico_switcher" / "pico_cli.py": 100}
        for file_path in sorted(cli_root.glob("*.py")):
            file_limits[file_path] = 500

        for file_path, limit in file_limits.items():
            with file_path.open("r", encoding="utf-8") as handle:
                line_count = sum(1 for _ in handle)
            self.assertLessEqual(line_count, limit, f"{file_path} exceeded {limit} lines")


if __name__ == "__main__":
    unittest.main()
