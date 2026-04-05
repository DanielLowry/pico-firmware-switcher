"""Small helper utilities shared by CLI modules.

These helpers are intentionally CLI-local rather than general-purpose service
code. They handle raw argv parsing, small profile/UF2 resolution helpers, path
expansion, and the short user-facing status lines printed by the CLI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..pico_profiles import Profile, require_profile_target, resolve_profile


def expand_path(path_value: str) -> Path:
    """Expand a user-provided path string to a filesystem path."""

    return Path(path_value).expanduser()


def extract_cli_option_value(argv: list[str], option_name: str) -> str | None:
    """Extract one option value from raw argv without fully parsing the CLI."""

    for index, item in enumerate(argv):
        if item == option_name:
            if index + 1 < len(argv):
                return argv[index + 1]
            return None
        if item.startswith(f"{option_name}="):
            return item.split("=", 1)[1]
    return None


def extract_switcher_config_value(argv: list[str]) -> str | None:
    """Extract `--config` only for commands that use it as switcher config."""

    command = extract_subcommand(argv)
    if command not in {
        "detect",
        "flash",
        "to-py",
        "sync-py",
        "build-cpp",
        "to-cpp",
        "install-py-files",
        "log-state",
        "install-state-timer",
    }:
        return None
    return extract_cli_option_value(argv, "--config")


def extract_subcommand(argv: list[str]) -> str | None:
    """Return the CLI subcommand from raw argv."""

    for item in argv:
        if not item.startswith("-"):
            return item
    return None


def resolve_profile_for_target(args: argparse.Namespace, target: str) -> Profile:
    """Resolve and validate the selected profile for the requested target."""

    profile = resolve_profile(args.switcher_config, getattr(args, "profile", None))
    require_profile_target(profile, target)
    return profile


def resolve_switch_uf2_path(args: argparse.Namespace, *, target: str, profile: Profile) -> Path:
    """Resolve the UF2 path used by a switch command.

    Managed C++ now defaults to the selected profile's declared `output_uf2`,
    which is the path produced by `build-cpp` or `to-cpp --build`. A manual
    `--uf2` still overrides that behavior for ad-hoc flashing.
    """

    if target == "cpp":
        if args.uf2:
            return expand_path(args.uf2)
        assert profile.cpp is not None  # covered by require_profile_target
        uf2_path = profile.cpp.output_uf2
        if not uf2_path.exists():
            raise RuntimeError(f"C++ UF2 not found: {uf2_path}. Run `build-cpp` or use `to-cpp --build`.")
        return uf2_path

    return expand_path(args.uf2)


def print_switch_result(target: str, flashed: bool) -> None:
    """Print the post-switch status line shown to CLI users."""

    if target == "py":
        print("Switched to MicroPython UF2." if flashed else "Already in MicroPython mode; skipped UF2 flash.")
        return
    print("Switched to C++ UF2." if flashed else "Already in C++ mode; skipped UF2 flash.")


def print_py_sync_result(profile_name: str) -> None:
    """Print the post-sync status line shown to CLI users."""

    print(f"Synced managed MicroPython profile: {profile_name}")


def print_cpp_build_result(profile_name: str, output_uf2: Path) -> None:
    """Print the post-build status line shown to CLI users."""

    print(f"Built managed C++ profile: {profile_name} -> {output_uf2}")
