"""Managed C++ build planning and execution for profile-based deployment.

This module is the host-side counterpart to the managed C++ runtime. It
validates the small client contract, plans a per-profile CMake build, invokes
that build, and copies the resulting UF2 to the profile's configured output
path so the existing flash workflow can consume it.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import PROJECT_ROOT, RUNTIME_ROOT
from .pico_cpp_contract import (
    CPP_BOOTSEL_COMMAND,
    CPP_CLIENT_ENTRY_SYMBOL,
    CPP_CLIENT_HEADER_NAME,
)
from .pico_profiles import CppProfile, ProfileConfigError


MANAGED_CPP_CMAKE_DIR = PROJECT_ROOT / "cpp"
MANAGED_CPP_BUILD_ROOT = RUNTIME_ROOT / "cpp-builds"
MANAGED_CPP_TARGET_NAME = "bootloader_trigger"
MANAGED_CPP_RUNTIME_SOURCE = MANAGED_CPP_CMAKE_DIR / "managed_runtime.cpp"
MANAGED_CPP_CLIENT_HEADER = MANAGED_CPP_CMAKE_DIR / CPP_CLIENT_HEADER_NAME

_CLIENT_ENTRY_PATTERN = re.compile(r"\b" + re.escape(CPP_CLIENT_ENTRY_SYMBOL) + r"\s*\(")
_MAIN_PATTERN = re.compile(r"\b(?:int|void)\s+main\s*\(")


@dataclass(frozen=True)
class ManagedCppBuildPlan:
    """Resolved build inputs for one managed C++ profile."""

    profile_name: str
    source_dir: Path
    sources: tuple[Path, ...]
    output_uf2: Path
    build_dir: Path
    target_name: str
    output_name: str
    runtime_source: Path
    client_header: Path


def build_managed_cpp_plan(
    profile_name: str,
    cpp_profile: CppProfile,
    *,
    build_root: Path | None = None,
) -> ManagedCppBuildPlan:
    """Validate one C++ profile and return its managed build plan.

    The required client interface is intentionally small:
    - one or more source files listed in the profile
    - exactly one client-owned entry symbol: `client_app_main()`
    - no client-defined `main()` because the switcher runtime owns process start
    """

    _validate_cpp_client_contract(cpp_profile)

    output_uf2 = cpp_profile.output_uf2.resolve()
    if output_uf2.suffix.lower() != ".uf2":
        raise ProfileConfigError(f"C++ profile output_uf2 must end with .uf2: {output_uf2}")

    resolved_build_root = (build_root or MANAGED_CPP_BUILD_ROOT).resolve()
    return ManagedCppBuildPlan(
        profile_name=profile_name,
        source_dir=cpp_profile.source_dir.resolve(),
        sources=tuple(source_path.resolve() for source_path in cpp_profile.sources),
        output_uf2=output_uf2,
        build_dir=resolved_build_root / profile_name,
        target_name=MANAGED_CPP_TARGET_NAME,
        output_name=output_uf2.stem,
        runtime_source=MANAGED_CPP_RUNTIME_SOURCE,
        client_header=MANAGED_CPP_CLIENT_HEADER,
    )


def build_managed_cpp_profile(plan: ManagedCppBuildPlan, *, verbose: bool) -> Path:
    """Build one managed C++ profile and copy its UF2 to the configured output."""

    plan.build_dir.mkdir(parents=True, exist_ok=True)
    plan.output_uf2.parent.mkdir(parents=True, exist_ok=True)

    client_sources_arg = ";".join(str(source_path) for source_path in plan.sources)
    configure_cmd = [
        "cmake",
        "-S",
        str(MANAGED_CPP_CMAKE_DIR),
        "-B",
        str(plan.build_dir),
        f"-DPICO_SWITCHER_PROFILE_NAME={plan.profile_name}",
        f"-DPICO_SWITCHER_OUTPUT_NAME={plan.output_name}",
        f"-DPICO_SWITCHER_BOOTSEL_COMMAND={CPP_BOOTSEL_COMMAND}",
        f"-DPICO_SWITCHER_CLIENT_SOURCES={client_sources_arg}",
    ]
    build_cmd = [
        "cmake",
        "--build",
        str(plan.build_dir),
        "--target",
        plan.target_name,
    ]

    _run_cmake(configure_cmd, verbose=verbose)
    _run_cmake(build_cmd, verbose=verbose)

    built_uf2 = plan.build_dir / f"{plan.output_name}.uf2"
    if not built_uf2.exists():
        raise RuntimeError(f"Managed C++ build did not produce UF2: {built_uf2}")

    shutil.copy2(built_uf2, plan.output_uf2)
    return plan.output_uf2


def _validate_cpp_client_contract(cpp_profile: CppProfile) -> None:
    """Validate the small managed C++ client contract before invoking CMake."""

    has_client_entry = False

    for source_path in cpp_profile.sources:
        source_text = source_path.read_text(encoding="utf-8")
        if _CLIENT_ENTRY_PATTERN.search(source_text):
            has_client_entry = True
        if _MAIN_PATTERN.search(source_text):
            raise ProfileConfigError(
                "Managed C++ clients must not define main(); the switcher runtime owns startup"
            )

    if not has_client_entry:
        raise ProfileConfigError(
            f"Managed C++ profile is missing required {CPP_CLIENT_ENTRY_SYMBOL}() definition"
        )


def _run_cmake(cmd: list[str], *, verbose: bool) -> None:
    """Run one CMake command with readable error reporting."""

    if verbose:
        print(shlex.join(cmd))
    result = subprocess.run(cmd, check=False, capture_output=not verbose, text=True)
    if result.returncode == 0:
        return

    err = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(f"CMake failed: {shlex.join(cmd)}{(': ' + err) if err else ''}")
