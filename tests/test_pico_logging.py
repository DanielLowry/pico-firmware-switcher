from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pico_switcher.pico_log import EventRecorder, PicoLogStore, default_db_path
from pico_switcher.pico_systemd import install_state_timer, render_state_timer


class PicoLogStoreTests(unittest.TestCase):
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
