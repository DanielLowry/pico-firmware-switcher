"""Managed MicroPython packaging and sync helpers.

In this repo, "managed runtime structure" means the switcher controls the
on-device startup layout and the client is placed into a dedicated application
area:

- switcher-owned device root files:
  - `boot.py`
  - `main.py`
  - `_switcher_profile.py`
- client-owned device application area:
  - `/app/...`

This module owns the Phase 2 MicroPython deployment model built around that
structure: copy the static switcher-owned runtime templates, load the repo-side
helper script used to clear `/app`, generate the profile-specific metadata
file, validate the configured client entrypoint, stage the client source tree
under `/app`, and sync that managed layout to the Pico via `mpremote`.
"""

from __future__ import annotations

import ast
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import PROJECT_ROOT
from .pico_mpremote import run_mpremote
from .pico_profiles import ProfileConfigError, PythonProfile


MANAGED_METADATA_MODULE_NAME = "_switcher_profile"
MANAGED_METADATA_FILE_NAME = f"{MANAGED_METADATA_MODULE_NAME}.py"
MANAGED_BOOT_FILE_NAME = "boot.py"
MANAGED_MAIN_FILE_NAME = "main.py"
MANAGED_APP_DIR_NAME = "app"
MANAGED_APP_ROOT = "/app"
MANAGED_REMOVE_APP_SCRIPT_FILE = PROJECT_ROOT / "py" / "remove_app.py"
# Static switcher-owned root files copied as-is from the repo to the Pico.
MANAGED_RUNTIME_TEMPLATE_FILES = {
    MANAGED_BOOT_FILE_NAME: PROJECT_ROOT / "py" / MANAGED_BOOT_FILE_NAME,
    MANAGED_MAIN_FILE_NAME: PROJECT_ROOT / "py" / MANAGED_MAIN_FILE_NAME,
}


@dataclass(frozen=True)
class ManagedPythonSyncPlan:
    """Resolved managed MicroPython bundle for one profile.

    The plan represents one concrete on-device deployment:

    - static switcher-owned runtime templates copied to the device root
    - one generated metadata file at the device root
    - one client source tree staged under `/app`
    """

    profile_name: str
    source_dir: Path
    entry_module: str
    entry_function: str
    runtime_template_files: dict[str, Path]
    generated_files: dict[str, str]


def build_managed_python_sync_plan(profile_name: str, python_profile: PythonProfile) -> ManagedPythonSyncPlan:
    """Build and validate the managed MicroPython sync plan for one profile.

    This is where the repo turns a client profile into the managed runtime
    structure that will exist on the Pico filesystem.

    File responsibilities in the returned plan:

    - `runtime_template_files` contains static repo files that are copied
      directly to the Pico root:
      - `boot.py`
      - `main.py`
    - `generated_files` contains files rendered from Python code at sync time:
      - `_switcher_profile.py`
    """

    module_source = resolve_entry_module_source(python_profile)
    ensure_python_entrypoint_exists(
        module_source=module_source,
        entry_function=python_profile.entry_function,
        profile_name=profile_name,
    )

    generated_files = {
        MANAGED_METADATA_FILE_NAME: render_managed_metadata_py(
            profile_name=profile_name,
            entry_module=python_profile.entry_module,
            entry_function=python_profile.entry_function,
        ),
    }
    return ManagedPythonSyncPlan(
        profile_name=profile_name,
        source_dir=python_profile.source_dir,
        entry_module=python_profile.entry_module,
        entry_function=python_profile.entry_function,
        runtime_template_files=dict(MANAGED_RUNTIME_TEMPLATE_FILES),
        generated_files=generated_files,
    )


def resolve_entry_module_source(python_profile: PythonProfile) -> Path:
    """Resolve the local source file for one configured entry module."""

    module_parts = python_profile.entry_module.split(".")
    module_file = python_profile.source_dir.joinpath(*module_parts).with_suffix(".py")
    package_init = python_profile.source_dir.joinpath(*module_parts, "__init__.py")
    if module_file.exists():
        return module_file
    if package_init.exists():
        return package_init
    raise ProfileConfigError(
        f"Python entry module {python_profile.entry_module!r} not found under {python_profile.source_dir}"
    )


def ensure_python_entrypoint_exists(*, module_source: Path, entry_function: str, profile_name: str) -> None:
    """Require the configured entry function to exist in the resolved module."""

    try:
        tree = ast.parse(module_source.read_text(encoding="utf-8"), filename=str(module_source))
    except SyntaxError as exc:
        raise ProfileConfigError(
            f"Profile {profile_name!r} entry module has invalid Python syntax: {module_source}: {exc}"
        ) from exc

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_function:
            return

    raise ProfileConfigError(
        f"Profile {profile_name!r} is missing Python entry function {entry_function!r} in {module_source}"
    )


def render_managed_metadata_py(*, profile_name: str, entry_module: str, entry_function: str) -> str:
    """Return the generated switcher-owned profile metadata module.

    This root-level file lets the switcher runtime know which client profile is
    active and which client entrypoint should be invoked from `/app`.

    This is currently the only managed MicroPython root file that is generated
    dynamically per profile. `boot.py` and `main.py` are copied from static repo
    templates instead.
    """

    return "\n".join(
        (
            '"""Generated switcher profile metadata for managed MicroPython deployments."""',
            "",
            f"PROFILE_NAME = {profile_name!r}",
            "MANAGED = True",
            f"APP_ROOT = {MANAGED_APP_ROOT!r}",
            f"ENTRY_MODULE = {entry_module!r}",
            f"ENTRY_FUNCTION = {entry_function!r}",
            "",
        )
    )


def sync_managed_python_profile(
    *,
    port: str,
    plan: ManagedPythonSyncPlan,
    verbose: bool = False,
) -> None:
    """Sync the managed MicroPython runtime files and client app to the device.

    The resulting device layout is the managed runtime structure:

    - root: switcher-owned `boot.py`, `main.py`, `_switcher_profile.py`
    - `/app`: the synced client source tree

    Sync behavior by file type:

    - `_remove_remote_app_dir()` clears the previous client-owned `/app` tree
      using the repo-side helper script in `py/remove_app.py`
    - `_copy_client_tree()` stages the new client-owned `/app` tree locally
    - `runtime_template_files` are copied as static root files
    - `generated_files` are rendered to temp files, then copied to the root
    """

    with tempfile.TemporaryDirectory(prefix="pico-switcher-py-") as tmpdir:
        staging_root = Path(tmpdir)
        app_stage_dir = staging_root / MANAGED_APP_DIR_NAME
        _copy_client_tree(source_dir=plan.source_dir, destination_dir=app_stage_dir)

        _remove_remote_app_dir(port=port, verbose=verbose)
        run_mpremote(["connect", port, "fs", "cp", "-r", str(app_stage_dir), ":"], quiet=not verbose)

        for file_name, file_path in plan.runtime_template_files.items():
            run_mpremote(["connect", port, "fs", "cp", str(file_path), ":"], quiet=not verbose)

        for file_name, content in plan.generated_files.items():
            staged_file = staging_root / file_name
            staged_file.write_text(content, encoding="utf-8")
            run_mpremote(["connect", port, "fs", "cp", str(staged_file), ":"], quiet=not verbose)


def _copy_client_tree(*, source_dir: Path, destination_dir: Path) -> None:
    """Copy the client source tree into a temporary staging directory."""

    shutil.copytree(
        source_dir,
        destination_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        dirs_exist_ok=False,
    )


def _remove_remote_app_dir(*, port: str, verbose: bool) -> None:
    """Best-effort recursive removal of the managed remote `/app` directory."""

    removal_script = _load_remove_app_script()
    run_mpremote(["connect", port, "exec", removal_script], quiet=not verbose)


def _load_remove_app_script() -> str:
    """Load the repo-side MicroPython helper used to clear the remote `/app` tree."""

    try:
        return MANAGED_REMOVE_APP_SCRIPT_FILE.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing managed MicroPython removal script: {MANAGED_REMOVE_APP_SCRIPT_FILE}") from exc
