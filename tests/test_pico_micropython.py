"""Unit tests for managed MicroPython sync planning and trigger behavior.

These tests verify the static switcher-owned runtime template planning,
generated metadata content, lightweight entrypoint validation, `mpremote`
command planning for `/app` sync, and the host-driven MicroPython bootloader
trigger path.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pico_switcher.pico_micropython import (
    MANAGED_BOOT_FILE_NAME,
    MANAGED_MAIN_FILE_NAME,
    MANAGED_METADATA_FILE_NAME,
    build_managed_python_sync_plan,
    sync_managed_python_profile,
)
from pico_switcher.pico_mpremote import trigger_from_py
from pico_switcher.pico_profiles import ProfileConfigError, PythonProfile


class ManagedMicroPythonPlanTests(unittest.TestCase):
    def test_build_sync_plan_generates_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "client"
            source_dir.mkdir()
            (source_dir / "blink.py").write_text(
                "\n".join(
                    (
                        "def main():",
                        "    print('blink')",
                    )
                ),
                encoding="utf-8",
            )

            plan = build_managed_python_sync_plan(
                "blink",
                PythonProfile(
                    source_dir=source_dir,
                    entry_module="blink",
                    entry_function="main",
                ),
            )

            self.assertEqual(plan.profile_name, "blink")
            self.assertEqual(
                set(plan.runtime_template_files),
                {MANAGED_BOOT_FILE_NAME, MANAGED_MAIN_FILE_NAME},
            )
            self.assertTrue(plan.runtime_template_files[MANAGED_BOOT_FILE_NAME].name == MANAGED_BOOT_FILE_NAME)
            self.assertTrue(plan.runtime_template_files[MANAGED_MAIN_FILE_NAME].name == MANAGED_MAIN_FILE_NAME)
            self.assertEqual(set(plan.generated_files), {MANAGED_METADATA_FILE_NAME})
            self.assertIn("ENTRY_MODULE = 'blink'", plan.generated_files[MANAGED_METADATA_FILE_NAME])

    def test_build_sync_plan_rejects_missing_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "client"
            source_dir.mkdir()
            (source_dir / "blink.py").write_text(
                "\n".join(
                    (
                        "def other():",
                        "    pass",
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ProfileConfigError) as ctx:
                build_managed_python_sync_plan(
                    "blink",
                    PythonProfile(
                        source_dir=source_dir,
                        entry_module="blink",
                        entry_function="main",
                    ),
                )

            self.assertIn("missing Python entry function", str(ctx.exception))

    def test_sync_profile_runs_expected_mpremote_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "client"
            source_dir.mkdir()
            (source_dir / "blink.py").write_text(
                "\n".join(
                    (
                        "def main():",
                        "    print('blink')",
                    )
                ),
                encoding="utf-8",
            )
            plan = build_managed_python_sync_plan(
                "blink",
                PythonProfile(
                    source_dir=source_dir,
                    entry_module="blink",
                    entry_function="main",
                ),
            )

            with mock.patch("pico_switcher.pico_micropython.run_mpremote") as run_mock:
                sync_managed_python_profile(port="/dev/ttyACM0", plan=plan, verbose=False)

            self.assertEqual(run_mock.call_count, 5)
            first_args = run_mock.call_args_list[0].args[0]
            second_args = run_mock.call_args_list[1].args[0]
            self.assertEqual(first_args[:3], ["connect", "/dev/ttyACM0", "exec"])
            self.assertIn("/app", first_args[3])
            self.assertEqual(second_args[:5], ["connect", "/dev/ttyACM0", "fs", "cp", "-r"])
            self.assertTrue(second_args[5].endswith("/app"))
            self.assertEqual(second_args[6], ":")

            copied_names = [Path(call.args[0][4]).name for call in run_mock.call_args_list[2:]]
            self.assertEqual(
                copied_names,
                [MANAGED_BOOT_FILE_NAME, MANAGED_MAIN_FILE_NAME, MANAGED_METADATA_FILE_NAME],
            )
            self.assertTrue(all(call.args[0][5] == ":" for call in run_mock.call_args_list[2:]))


class MicroPythonTriggerTests(unittest.TestCase):
    def test_trigger_from_py_uses_mpremote_bootloader(self) -> None:
        process = mock.Mock(returncode=0)
        with mock.patch("pico_switcher.pico_mpremote.resolve_serial_port", return_value="/dev/ttyACM0"), mock.patch(
            "pico_switcher.pico_mpremote.run_mpremote",
            return_value=process,
        ) as run_mock:
            result = trigger_from_py(port="auto", verbose=False)

        self.assertIsNone(result)
        run_mock.assert_called_once_with(
            ["connect", "/dev/ttyACM0", "bootloader"],
            quiet=True,
            allow_error=True,
        )


if __name__ == "__main__":
    unittest.main()
