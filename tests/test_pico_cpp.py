"""Unit tests for the managed C++ profile contract and build planning.

These tests keep the C++ phase lightweight: they validate the required client
entrypoint, reject obvious contract violations such as a client-defined
`main()`, and verify the host-side CMake command planning without running a
real Pico SDK build in CI.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pico_switcher.pico_cpp import (
    MANAGED_CPP_TARGET_NAME,
    build_managed_cpp_plan,
    build_managed_cpp_profile,
)
from pico_switcher.pico_device import trigger_from_cpp
from pico_switcher.pico_profiles import CppProfile, ProfileConfigError


class ManagedCppPlanTests(unittest.TestCase):
    def test_build_plan_validates_client_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "client"
            source_dir.mkdir()
            source_file = source_dir / "client_app.cpp"
            source_file.write_text(
                "\n".join(
                    (
                        '#include "switcher_client.h"',
                        'extern "C" void client_app_main(void) {}',
                    )
                ),
                encoding="utf-8",
            )

            plan = build_managed_cpp_plan(
                "demo",
                CppProfile(
                    source_dir=source_dir,
                    sources=(source_file,),
                    output_uf2=Path(tmpdir) / "uf2s" / "demo.uf2",
                ),
                build_root=Path(tmpdir) / ".cpp-builds",
            )

            self.assertEqual(plan.profile_name, "demo")
            self.assertEqual(plan.target_name, MANAGED_CPP_TARGET_NAME)
            self.assertEqual(plan.output_name, "demo")
            self.assertEqual(plan.source_dir, source_dir.resolve())
            self.assertEqual(plan.sources, (source_file.resolve(),))
            self.assertEqual(plan.build_dir, (Path(tmpdir) / ".cpp-builds" / "demo").resolve())
            self.assertEqual(plan.client_header.name, "switcher_client.h")

    def test_build_plan_rejects_missing_client_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "client"
            source_dir.mkdir()
            source_file = source_dir / "client_app.cpp"
            source_file.write_text("void other(void) {}\n", encoding="utf-8")

            with self.assertRaises(ProfileConfigError) as ctx:
                build_managed_cpp_plan(
                    "demo",
                    CppProfile(
                        source_dir=source_dir,
                        sources=(source_file,),
                        output_uf2=Path(tmpdir) / "uf2s" / "demo.uf2",
                    ),
                )

            self.assertIn("client_app_main", str(ctx.exception))

    def test_build_plan_rejects_client_defined_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "client"
            source_dir.mkdir()
            source_file = source_dir / "client_app.cpp"
            source_file.write_text(
                "\n".join(
                    (
                        "int main() { return 0; }",
                        'extern "C" void client_app_main(void) {}',
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ProfileConfigError) as ctx:
                build_managed_cpp_plan(
                    "demo",
                    CppProfile(
                        source_dir=source_dir,
                        sources=(source_file,),
                        output_uf2=Path(tmpdir) / "uf2s" / "demo.uf2",
                    ),
                )

            self.assertIn("must not define main()", str(ctx.exception))


class ManagedCppBuildTests(unittest.TestCase):
    def test_build_profile_runs_expected_cmake_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "client"
            source_dir.mkdir()
            source_file = source_dir / "client_app.cpp"
            source_file.write_text(
                'extern "C" void client_app_main(void) {}\n',
                encoding="utf-8",
            )

            plan = build_managed_cpp_plan(
                "demo",
                CppProfile(
                    source_dir=source_dir,
                    sources=(source_file,),
                    output_uf2=root / "uf2s" / "demo.uf2",
                ),
                build_root=root / ".cpp-builds",
            )

            cmake_calls: list[list[str]] = []

            def fake_run_cmake(cmd: list[str], *, verbose: bool) -> None:
                cmake_calls.append(cmd)
                if cmd[:2] == ["cmake", "--build"]:
                    built_uf2 = plan.build_dir / f"{plan.output_name}.uf2"
                    built_uf2.parent.mkdir(parents=True, exist_ok=True)
                    built_uf2.write_bytes(b"managed-uf2")

            with mock.patch("pico_switcher.pico_cpp._run_cmake", side_effect=fake_run_cmake):
                output_uf2 = build_managed_cpp_profile(plan, verbose=False)

            self.assertEqual(output_uf2, plan.output_uf2)
            self.assertEqual(output_uf2.read_bytes(), b"managed-uf2")
            self.assertEqual(len(cmake_calls), 2)
            self.assertEqual(cmake_calls[1], ["cmake", "--build", str(plan.build_dir), "--target", plan.target_name])
            self.assertTrue(any(arg.endswith(str(source_file.resolve())) for arg in cmake_calls[0]))


class ManagedCppTriggerTests(unittest.TestCase):
    def test_trigger_from_cpp_sends_managed_command_and_legacy_fallback(self) -> None:
        serial_handle = mock.MagicMock()
        serial_context = mock.MagicMock()
        serial_context.__enter__.return_value = serial_handle

        with mock.patch("pico_switcher.pico_device.resolve_serial_port", return_value="/dev/ttyACM0"), mock.patch(
            "pico_switcher.pico_device.serial.Serial",
            return_value=serial_context,
        ):
            trigger_from_cpp(port="auto", verbose=False)

        serial_handle.write.assert_has_calls(
            [
                mock.call(b"BOOTSEL\n"),
                mock.call(b"b"),
            ]
        )
        serial_handle.flush.assert_called_once()


if __name__ == "__main__":
    unittest.main()
