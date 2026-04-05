"""Unit tests for logging, backup, and timer helpers.

These tests focus on lightweight host-side behavior that can be validated
without hardware: SQLite logging, config parsing, backup command construction,
and generated `systemd` unit content.
"""

from __future__ import annotations

import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from subprocess import CalledProcessError
from unittest import mock

from pico_switcher.pico_backup import (
    BackupConfig,
    BackupRemoteConfig,
    BackupTransferError,
    backup_database,
    default_backup_config_path,
    load_backup_config,
)
from pico_switcher import RUNTIME_ROOT
from pico_switcher.cli.history import print_history_section
from pico_switcher.pico_log import EventRecorder, PicoLogStore, default_db_path
from pico_switcher.pico_systemd import install_state_timer, render_state_timer


class PicoLogStoreTests(unittest.TestCase):
    def test_default_db_path_is_repo_local_without_override(self) -> None:
        original = os.environ.get("PICO_SWITCHER_DB")
        os.environ.pop("PICO_SWITCHER_DB", None)
        try:
            self.assertEqual(default_db_path(), RUNTIME_ROOT / "events.sqlite3")
        finally:
            if original is not None:
                os.environ["PICO_SWITCHER_DB"] = original

    def test_recorder_persists_events_and_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "events.sqlite3"
            store = PicoLogStore(db_path)
            recorder = EventRecorder(store=store, source="test")

            recorder.event(
                "switch_requested",
                mode="py",
                target_mode="cpp",
                port="/dev/ttyACM0",
                message="Switch requested",
                details={"force_flash": False},
            )
            recorder.snapshot(
                mode="cpp",
                port="/dev/ttyACM0",
                source="timer",
                message="Recorded snapshot",
                details={"status": "ok"},
            )

            events = store.fetch_events(limit=5)
            snapshots = store.fetch_snapshots(limit=5)

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "switch_requested")
            self.assertEqual(events[0]["mode"], "py")
            self.assertEqual(events[0]["target_mode"], "cpp")
            self.assertEqual(events[0]["details"], {"force_flash": False})

            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["source"], "timer")
            self.assertEqual(snapshots[0]["mode"], "cpp")
            self.assertEqual(snapshots[0]["details"], {"status": "ok"})

            recorder.close()

    def test_default_db_path_honours_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = str(Path(tmpdir) / "override.sqlite3")
            original = os.environ.get("PICO_SWITCHER_DB")
            os.environ["PICO_SWITCHER_DB"] = env_path
            try:
                self.assertEqual(default_db_path(), Path(env_path))
            finally:
                if original is None:
                    os.environ.pop("PICO_SWITCHER_DB", None)
                else:
                    os.environ["PICO_SWITCHER_DB"] = original


class PicoBackupTests(unittest.TestCase):
    def test_default_backup_config_path_is_repo_local(self) -> None:
        self.assertEqual(default_backup_config_path(), RUNTIME_ROOT / "backup.toml")

    def test_load_backup_config_reads_expected_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "backup.toml"
            ssh_key_path = Path(tmpdir) / "backup-key"
            ssh_key_path.write_text("test-key", encoding="utf-8")
            config_path.write_text(
                "\n".join(
                    (
                        "[local]",
                        'staging_dir = "staging"',
                        "compress = false",
                        "",
                        "[remote]",
                        'host = "backup-box.local"',
                        'user = "backuponly"',
                        'path = "/srv/pico/backups"',
                        'ssh_key_path = "backup-key"',
                        "port = 2222",
                        "connect_timeout_seconds = 7",
                    )
                ),
                encoding="utf-8",
            )

            config = load_backup_config(config_path)

            self.assertEqual(config.staging_dir, Path(tmpdir) / "staging")
            self.assertFalse(config.compress)
            self.assertEqual(config.remote.host, "backup-box.local")
            self.assertEqual(config.remote.user, "backuponly")
            self.assertEqual(config.remote.path, "/srv/pico/backups")
            self.assertEqual(config.remote.ssh_key_path, ssh_key_path.resolve())
            self.assertEqual(config.remote.ssh_port, 2222)
            self.assertEqual(config.remote.connect_timeout_seconds, 7)

    def test_backup_database_creates_consistent_snapshot_and_transfers_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "events.sqlite3"
            staging_dir = Path(tmpdir) / "staging"
            ssh_key_path = Path(tmpdir) / "backup-key"
            ssh_key_path.write_text("test-key", encoding="utf-8")

            store = PicoLogStore(db_path)
            store.log_event(
                run_id="run-1",
                source="test",
                event_type="detect_mode",
                status="ok",
                mode="py",
                port="/dev/ttyACM0",
                message="Detected mode",
                details={"reason": "test"},
            )
            store.close()

            config = BackupConfig(
                staging_dir=staging_dir,
                compress=False,
                remote=BackupRemoteConfig(
                    host="backup-box.local",
                    user="backuponly",
                    path="/srv/pico/backups",
                    ssh_key_path=ssh_key_path,
                ),
            )

            def fake_run(command: list[str], check: bool) -> None:
                self.assertTrue(check)
                self.assertEqual(command[0], "rsync")
                self.assertIn("--protect-args", command)
                source_artifact = Path(command[-2])
                self.assertTrue(source_artifact.exists())
                self.assertEqual(source_artifact.suffix, ".sqlite3")

                backup_conn = sqlite3.connect(source_artifact)
                try:
                    row_count = backup_conn.execute("select count(*) from event_log").fetchone()[0]
                finally:
                    backup_conn.close()
                self.assertEqual(row_count, 1)
                self.assertEqual(
                    command[-1],
                    f"backuponly@backup-box.local:/srv/pico/backups/{source_artifact.name}",
                )

            with mock.patch("pico_switcher.pico_backup.subprocess.run", side_effect=fake_run) as run_mock:
                result = backup_database(db_path=db_path, config=config)

            run_mock.assert_called_once()
            self.assertEqual(result.file_name.count(".sqlite3"), 1)
            self.assertEqual(result.remote_uri.split(":")[0], "backuponly@backup-box.local")
            self.assertFalse((staging_dir / result.file_name).exists())

    def test_backup_database_leaves_local_copy_when_transfer_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "events.sqlite3"
            staging_dir = Path(tmpdir) / "staging"
            ssh_key_path = Path(tmpdir) / "backup-key"
            ssh_key_path.write_text("test-key", encoding="utf-8")

            store = PicoLogStore(db_path)
            store.log_snapshot(
                run_id="run-1",
                source="test",
                mode="cpp",
                port="/dev/ttyACM0",
                message="Recorded snapshot",
                details={"status": "ok"},
            )
            store.close()

            config = BackupConfig(
                staging_dir=staging_dir,
                compress=True,
                remote=BackupRemoteConfig(
                    host="backup-box.local",
                    user="backuponly",
                    path="/srv/pico/backups",
                    ssh_key_path=ssh_key_path,
                ),
            )

            with mock.patch(
                "pico_switcher.pico_backup.subprocess.run",
                side_effect=CalledProcessError(returncode=1, cmd=["rsync"]),
            ):
                with self.assertRaises(BackupTransferError) as ctx:
                    backup_database(db_path=db_path, config=config)

            self.assertTrue(ctx.exception.staged_path.exists())
            self.assertEqual(ctx.exception.staged_path.suffix, ".gz")

    def test_backup_database_preserves_remote_paths_with_spaces_and_apostrophes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "events.sqlite3"
            staging_dir = Path(tmpdir) / "staging"
            ssh_key_path = Path(tmpdir) / "backup-key"
            ssh_key_path.write_text("test-key", encoding="utf-8")

            store = PicoLogStore(db_path)
            store.log_event(
                run_id="run-1",
                source="test",
                event_type="backup_test",
                status="ok",
                message="Test row",
            )
            store.close()

            config = BackupConfig(
                staging_dir=staging_dir,
                compress=True,
                remote=BackupRemoteConfig(
                    host="backup-box.local",
                    user="backuponly",
                    path="/home/dan/Drive/Dan's Googly Drive/pico_backups",
                    ssh_key_path=ssh_key_path,
                ),
            )

            def fake_run(command: list[str], check: bool) -> None:
                self.assertTrue(check)
                self.assertIn("--protect-args", command)
                self.assertFalse(command[-1].startswith("backuponly@backup-box.local:'"))
                self.assertNotIn('"\'"\'"', command[-1])
                self.assertIn("/home/dan/Drive/Dan's Googly Drive/pico_backups/", command[-1])

            with mock.patch("pico_switcher.pico_backup.subprocess.run", side_effect=fake_run):
                result = backup_database(db_path=db_path, config=config)

            self.assertIn("/home/dan/Drive/Dan's Googly Drive/pico_backups/", result.remote_uri)


class PicoCliHistoryTests(unittest.TestCase):
    def test_history_output_is_compact_by_default(self) -> None:
        row = {
            "created_at": "2026-03-29T18:06:09+00:00",
            "status": "ok",
            "event_type": "backup_requested",
            "source": "backup-db",
            "mode": None,
            "target_mode": None,
            "port": None,
            "mountpoint": None,
            "message": "SQLite backup requested",
            "details": {
                "config_path": str(RUNTIME_ROOT / "backup.toml"),
                "db_path": str(RUNTIME_ROOT / "events.sqlite3"),
                "remote_host": "192.168.68.79",
                "remote_path": "/home/dan/Drive/Dan's Googly Drive/pico_backups",
            },
        }

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_history_section("Events", [row], event_rows=True)

        output = buffer.getvalue()
        self.assertIn("2026-03-29T18:06:09Z", output)
        self.assertIn("cfg=.pico-switcher/backup.toml", output)
        self.assertIn("db=.pico-switcher/events.sqlite3", output)
        self.assertIn("host=192.168.68.79", output)
        self.assertIn("dest=pico_backups", output)
        self.assertNotIn("message=SQLite backup requested", output)
        self.assertNotIn("details={", output)
        self.assertNotIn("/home/dan/coding_projects/git/pico-firmware-switcher", output)

    def test_history_output_can_show_full_details(self) -> None:
        row = {
            "created_at": "2026-03-29T18:06:09+00:00",
            "status": "ok",
            "event_type": "backup_requested",
            "source": "backup-db",
            "mode": None,
            "target_mode": None,
            "port": None,
            "mountpoint": None,
            "message": "SQLite backup requested",
            "details": {
                "config_path": str(RUNTIME_ROOT / "backup.toml"),
                "db_path": str(RUNTIME_ROOT / "events.sqlite3"),
            },
        }

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_history_section("Events", [row], event_rows=True, full_details=True)

        output = buffer.getvalue()
        self.assertIn("message=SQLite backup requested", output)
        self.assertIn('details={"config_path":', output)


class PicoSystemdTests(unittest.TestCase):
    def test_install_state_timer_writes_expected_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            unit_dir = Path(tmpdir) / "units"
            repo_root.mkdir()

            units = install_state_timer(
                repo_root=repo_root,
                python_executable=Path("/usr/bin/python3"),
                db_path=Path(tmpdir) / "events.sqlite3",
                port="/dev/ttyACM0",
                timeout=2.5,
                unit_dir=unit_dir,
                service_name="pico-switcher-state",
                interval="5min",
            )

            self.assertTrue(units.service_path.exists())
            self.assertTrue(units.timer_path.exists())
            service_text = units.service_path.read_text(encoding="utf-8")
            timer_text = units.timer_path.read_text(encoding="utf-8")

            self.assertIn("pico.py log-state", service_text)
            self.assertIn("--port /dev/ttyACM0", service_text)
            self.assertIn("--timeout 2.5", service_text)
            self.assertIn("OnUnitActiveSec=5min", timer_text)

    def test_render_state_timer_targets_requested_service(self) -> None:
        timer_text = render_state_timer(service_name="custom-name", interval="10min")
        self.assertIn("Unit=custom-name.service", timer_text)
        self.assertIn("OnUnitActiveSec=10min", timer_text)


if __name__ == "__main__":
    unittest.main()
