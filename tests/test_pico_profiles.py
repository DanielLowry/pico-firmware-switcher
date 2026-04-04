"""Unit tests for Phase 1 profile discovery and validation.

These tests intentionally stay small and file-system based. They verify config
resolution, path handling, reserved-name checks, and profile target validation
without exercising real hardware or the full CLI workflow.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pico_switcher.pico_profiles import (
    CONFIG_ENV_VAR,
    CONFIG_FILE_NAME,
    DEFAULT_PROFILE_NAME,
    ProfileConfigError,
    discover_config_path,
    load_switcher_config,
    require_profile_target,
    resolve_profile,
)


class PicoProfileConfigTests(unittest.TestCase):
    def test_discover_config_prefers_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            explicit_path = Path(tmpdir) / CONFIG_FILE_NAME
            explicit_path.write_text("", encoding="utf-8")

            discovered = discover_config_path(explicit_path=str(explicit_path))

            self.assertEqual(discovered, explicit_path)

    def test_discover_config_uses_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / CONFIG_FILE_NAME
            config_path.write_text("", encoding="utf-8")

            discovered = discover_config_path(env={CONFIG_ENV_VAR: str(config_path)})

            self.assertEqual(discovered, config_path)

    def test_discover_config_searches_upward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested = root / "a" / "b" / "c"
            nested.mkdir(parents=True)
            config_path = root / CONFIG_FILE_NAME
            config_path.write_text("", encoding="utf-8")

            discovered = discover_config_path(cwd=nested)

            self.assertEqual(discovered, config_path)

    def test_load_without_file_returns_builtin_demo_profile(self) -> None:
        config = load_switcher_config(None)

        self.assertEqual(config.default_profile, DEFAULT_PROFILE_NAME)
        profile = resolve_profile(config, None)
        self.assertEqual(profile.name, DEFAULT_PROFILE_NAME)
        self.assertIsNotNone(profile.python)
        self.assertIsNotNone(profile.cpp)

    def test_load_config_resolves_relative_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as external_tmpdir:
            config_dir = Path(tmpdir)
            external_dir = Path(external_tmpdir)
            py_uf2 = config_dir / "firmware" / "micropython.uf2"
            cpp_uf2 = config_dir / "firmware" / "fallback.uf2"
            py_uf2.parent.mkdir(parents=True)
            py_uf2.write_bytes(b"py")
            cpp_uf2.write_bytes(b"cpp")

            python_source_dir = external_dir / "py_client"
            python_source_dir.mkdir()
            (python_source_dir / "blink.py").write_text("def main():\n    pass\n", encoding="utf-8")

            cpp_source_dir = config_dir / "cpp_client"
            cpp_source_dir.mkdir()
            (cpp_source_dir / "client_app.cpp").write_text("void client_app_main(void) {}\n", encoding="utf-8")

            config_path = config_dir / CONFIG_FILE_NAME
            config_path.write_text(
                "\n".join(
                    (
                        'default_profile = "client"',
                        "",
                        "[host]",
                        'port = "/dev/ttyUSB7"',
                        'mount_base = "/tmp/pico"',
                        'micropython_uf2 = "firmware/micropython.uf2"',
                        'cpp_uf2 = "firmware/fallback.uf2"',
                        "",
                        "[profiles.client.python]",
                        f'source_dir = "{python_source_dir}"',
                        'entry_module = "blink"',
                        "",
                        "[profiles.client.cpp]",
                        'source_dir = "cpp_client"',
                        'sources = ["client_app.cpp"]',
                        'output_uf2 = "build/client.uf2"',
                    )
                ),
                encoding="utf-8",
            )

            config = load_switcher_config(config_path)
            profile = resolve_profile(config, "client")

            self.assertEqual(config.host.port, "/dev/ttyUSB7")
            self.assertEqual(config.host.mount_base, "/tmp/pico")
            self.assertEqual(config.host.micropython_uf2, py_uf2.resolve())
            self.assertEqual(config.host.cpp_uf2, cpp_uf2.resolve())
            self.assertEqual(profile.python.source_dir, python_source_dir)
            self.assertEqual(profile.cpp.source_dir, cpp_source_dir.resolve())
            self.assertEqual(profile.cpp.sources, (cpp_source_dir.resolve() / "client_app.cpp",))
            self.assertEqual(profile.cpp.output_uf2, (config_dir / "build" / "client.uf2").resolve())

    def test_unknown_profile_raises_error(self) -> None:
        config = load_switcher_config(None)

        with self.assertRaises(ProfileConfigError):
            resolve_profile(config, "missing")

    def test_missing_profile_path_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            py_uf2 = config_dir / "micropython.uf2"
            cpp_uf2 = config_dir / "fallback.uf2"
            py_uf2.write_bytes(b"py")
            cpp_uf2.write_bytes(b"cpp")
            config_path = config_dir / CONFIG_FILE_NAME
            config_path.write_text(
                "\n".join(
                    (
                        'default_profile = "client"',
                        "",
                        "[host]",
                        'micropython_uf2 = "micropython.uf2"',
                        'cpp_uf2 = "fallback.uf2"',
                        "",
                        "[profiles.client.python]",
                        'source_dir = "missing_dir"',
                        'entry_module = "app"',
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ProfileConfigError) as ctx:
                load_switcher_config(config_path)

            self.assertIn("source_dir not found", str(ctx.exception))

    def test_reserved_python_root_files_raise_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            py_uf2 = config_dir / "micropython.uf2"
            cpp_uf2 = config_dir / "fallback.uf2"
            py_uf2.write_bytes(b"py")
            cpp_uf2.write_bytes(b"cpp")
            source_dir = config_dir / "py_client"
            source_dir.mkdir()
            (source_dir / "boot.py").write_text("print('reserved')\n", encoding="utf-8")

            config_path = config_dir / CONFIG_FILE_NAME
            config_path.write_text(
                "\n".join(
                    (
                        'default_profile = "client"',
                        "",
                        "[host]",
                        'micropython_uf2 = "micropython.uf2"',
                        'cpp_uf2 = "fallback.uf2"',
                        "",
                        "[profiles.client.python]",
                        'source_dir = "py_client"',
                        'entry_module = "app"',
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ProfileConfigError) as ctx:
                load_switcher_config(config_path)

            self.assertIn("reserved files", str(ctx.exception))

    def test_require_profile_target_rejects_missing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            py_uf2 = config_dir / "micropython.uf2"
            cpp_uf2 = config_dir / "fallback.uf2"
            py_uf2.write_bytes(b"py")
            cpp_uf2.write_bytes(b"cpp")
            source_dir = config_dir / "py_client"
            source_dir.mkdir()
            (source_dir / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")

            config_path = config_dir / CONFIG_FILE_NAME
            config_path.write_text(
                "\n".join(
                    (
                        'default_profile = "python_only"',
                        "",
                        "[host]",
                        'micropython_uf2 = "micropython.uf2"',
                        'cpp_uf2 = "fallback.uf2"',
                        "",
                        "[profiles.python_only.python]",
                        'source_dir = "py_client"',
                        'entry_module = "app"',
                    )
                ),
                encoding="utf-8",
            )

            config = load_switcher_config(config_path)
            profile = resolve_profile(config, "python_only")

            with self.assertRaises(ProfileConfigError):
                require_profile_target(profile, "cpp")


if __name__ == "__main__":
    unittest.main()
