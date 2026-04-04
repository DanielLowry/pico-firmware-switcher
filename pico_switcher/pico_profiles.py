"""Profile discovery, parsing, and validation for profile-based deployment.

This module owns the shared configuration model used by the profile-driven
switcher: locate `pico-switcher.toml`, load host defaults and named client
profiles, validate the Python and C++ contracts, and provide the built-in demo
profile used during migration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore

from . import PROJECT_ROOT
from .pico_device import DEFAULT_MOUNT_BASE, DEFAULT_PORT


CONFIG_ENV_VAR = "PICO_SWITCHER_CONFIG"
CONFIG_FILE_NAME = "pico-switcher.toml"
DEFAULT_PROFILE_NAME = "demo"
DEFAULT_PY_UF2 = PROJECT_ROOT / "uf2s" / "Pico-MicroPython-20250415-v1.25.0.uf2"
DEFAULT_CPP_UF2 = PROJECT_ROOT / "uf2s" / "bootloader_trigger.uf2"
DEFAULT_DEMO_PY_SOURCE_DIR = PROJECT_ROOT / "examples" / "demo_py"
DEFAULT_DEMO_CPP_SOURCE_DIR = PROJECT_ROOT / "examples" / "demo_cpp"
DEFAULT_DEMO_CPP_SOURCES = ("client_app.cpp",)
RESERVED_PYTHON_ROOT_FILES = frozenset({"boot.py", "main.py", "_switcher_profile.py"})


class ProfileConfigError(ValueError):
    """Raised when the profile configuration is missing or invalid."""


@dataclass(frozen=True)
class HostDefaults:
    """Host-level defaults used by CLI commands."""

    port: str = DEFAULT_PORT
    mount_base: str = DEFAULT_MOUNT_BASE
    device_id: str | None = None
    micropython_uf2: Path = DEFAULT_PY_UF2
    cpp_uf2: Path = DEFAULT_CPP_UF2


@dataclass(frozen=True)
class PythonProfile:
    """Managed MicroPython client contract."""

    source_dir: Path
    entry_module: str
    entry_function: str = "main"


@dataclass(frozen=True)
class CppProfile:
    """Managed C++ client contract."""

    source_dir: Path
    sources: tuple[Path, ...]
    output_uf2: Path


@dataclass(frozen=True)
class Profile:
    """One named deployable client profile."""

    name: str
    python: PythonProfile | None = None
    cpp: CppProfile | None = None
    built_in: bool = False


@dataclass(frozen=True)
class SwitcherConfig:
    """Resolved switcher configuration."""

    path: Path | None
    default_profile: str
    host: HostDefaults
    profiles: dict[str, Profile]


def discover_config_path(
    *,
    explicit_path: str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Discover the config file path from CLI, environment, or upward search."""

    if explicit_path:
        return Path(explicit_path).expanduser()

    resolved_env = env if env is not None else os.environ
    env_path = resolved_env.get(CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()

    search_dir = (cwd or Path.cwd()).expanduser().resolve()
    if search_dir.is_file():
        search_dir = search_dir.parent

    current = search_dir
    while True:
        candidate = current / CONFIG_FILE_NAME
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def load_switcher_config(config_path: Path | None) -> SwitcherConfig:
    """Load a config file or fall back to the built-in demo config."""

    if config_path is None:
        return _built_in_demo_config()

    resolved_path = config_path.expanduser()
    if not resolved_path.exists():
        raise ProfileConfigError(f"Config not found: {resolved_path}")

    with resolved_path.open("rb") as handle:
        raw_config = tomllib.load(handle)

    config_dir = resolved_path.parent
    host_section = _optional_mapping(raw_config.get("host"), "host", resolved_path)
    profiles_section = _require_mapping(raw_config, "profiles", resolved_path)
    default_profile = raw_config.get("default_profile", DEFAULT_PROFILE_NAME)
    if not isinstance(default_profile, str) or not default_profile.strip():
        raise ProfileConfigError(f"{resolved_path}: default_profile must be a non-empty string")

    profiles = {
        DEFAULT_PROFILE_NAME: _built_in_demo_profile(),
    }
    for profile_name, profile_value in profiles_section.items():
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ProfileConfigError(f"{resolved_path}: profile names must be non-empty strings")
        profiles[profile_name] = _load_profile(
            profile_name=profile_name,
            raw_profile=_require_mapping_in_parent(profile_value, f"profiles.{profile_name}", resolved_path),
            config_dir=config_dir,
            config_path=resolved_path,
        )

    if default_profile not in profiles:
        raise ProfileConfigError(
            f"{resolved_path}: default_profile {default_profile!r} does not match any configured profile"
        )

    return SwitcherConfig(
        path=resolved_path,
        default_profile=default_profile,
        host=_load_host_defaults(host_section, config_dir=config_dir, config_path=resolved_path),
        profiles=profiles,
    )


def resolve_profile(config: SwitcherConfig, profile_name: str | None) -> Profile:
    """Return the selected profile or raise a user-facing config error."""

    selected_name = profile_name or config.default_profile
    try:
        return config.profiles[selected_name]
    except KeyError as exc:
        raise ProfileConfigError(f"Unknown profile: {selected_name}") from exc


def require_profile_target(profile: Profile, target: str) -> None:
    """Ensure the selected profile supports the requested deployment target."""

    if target == "py" and profile.python is None:
        raise ProfileConfigError(f"Profile {profile.name!r} does not define a Python target")
    if target == "cpp" and profile.cpp is None:
        raise ProfileConfigError(f"Profile {profile.name!r} does not define a C++ target")


def _built_in_demo_config() -> SwitcherConfig:
    """Return the built-in demo config used before project config exists."""

    return SwitcherConfig(
        path=None,
        default_profile=DEFAULT_PROFILE_NAME,
        host=HostDefaults(),
        profiles={DEFAULT_PROFILE_NAME: _built_in_demo_profile()},
    )


def _built_in_demo_profile() -> Profile:
    """Return the built-in demo profile used as the migration fallback."""

    return Profile(
        name=DEFAULT_PROFILE_NAME,
        built_in=True,
        python=PythonProfile(
            source_dir=DEFAULT_DEMO_PY_SOURCE_DIR,
            entry_module="demo_app",
            entry_function="main",
        ),
        cpp=CppProfile(
            source_dir=DEFAULT_DEMO_CPP_SOURCE_DIR,
            sources=tuple(DEFAULT_DEMO_CPP_SOURCE_DIR / source for source in DEFAULT_DEMO_CPP_SOURCES),
            output_uf2=DEFAULT_CPP_UF2,
        ),
    )


def _load_host_defaults(
    raw_host: dict[str, object],
    *,
    config_dir: Path,
    config_path: Path,
) -> HostDefaults:
    """Load host defaults from the optional config section."""

    port = _optional_string(raw_host.get("port"), DEFAULT_PORT, "host.port", config_path)
    mount_base = _optional_string(raw_host.get("mount_base"), DEFAULT_MOUNT_BASE, "host.mount_base", config_path)
    device_id = _optional_string_or_none(raw_host.get("device_id"), "host.device_id", config_path)
    micropython_uf2 = _resolve_existing_path(
        raw_host.get("micropython_uf2"),
        default=DEFAULT_PY_UF2,
        config_dir=config_dir,
        field_name="host.micropython_uf2",
        config_path=config_path,
    )
    cpp_uf2 = _resolve_existing_path(
        raw_host.get("cpp_uf2"),
        default=DEFAULT_CPP_UF2,
        config_dir=config_dir,
        field_name="host.cpp_uf2",
        config_path=config_path,
    )
    return HostDefaults(
        port=port,
        mount_base=mount_base,
        device_id=device_id,
        micropython_uf2=micropython_uf2,
        cpp_uf2=cpp_uf2,
    )


def _load_profile(
    *,
    profile_name: str,
    raw_profile: dict[str, object],
    config_dir: Path,
    config_path: Path,
) -> Profile:
    """Load one named profile from config."""

    raw_python = raw_profile.get("python")
    raw_cpp = raw_profile.get("cpp")
    python_profile = None
    cpp_profile = None

    if raw_python is not None:
        python_profile = _load_python_profile(
            profile_name=profile_name,
            raw_python=_require_mapping_in_parent(raw_python, f"profiles.{profile_name}.python", config_path),
            config_dir=config_dir,
            config_path=config_path,
        )
    if raw_cpp is not None:
        cpp_profile = _load_cpp_profile(
            profile_name=profile_name,
            raw_cpp=_require_mapping_in_parent(raw_cpp, f"profiles.{profile_name}.cpp", config_path),
            config_dir=config_dir,
            config_path=config_path,
        )

    if python_profile is None and cpp_profile is None:
        raise ProfileConfigError(
            f"{config_path}: profiles.{profile_name} must define at least one of [python] or [cpp]"
        )

    return Profile(
        name=profile_name,
        python=python_profile,
        cpp=cpp_profile,
    )


def _load_python_profile(
    *,
    profile_name: str,
    raw_python: dict[str, object],
    config_dir: Path,
    config_path: Path,
) -> PythonProfile:
    """Load one Python profile contract."""

    source_dir = _resolve_required_directory(
        raw_python.get("source_dir"),
        config_dir=config_dir,
        field_name=f"profiles.{profile_name}.python.source_dir",
        config_path=config_path,
    )
    entry_module = _require_string(
        raw_python,
        "entry_module",
        f"profiles.{profile_name}.python.entry_module",
        config_path,
    )
    entry_function = _optional_string(
        raw_python.get("entry_function"),
        "main",
        f"profiles.{profile_name}.python.entry_function",
        config_path,
    )

    collisions = sorted(
        file_name for file_name in RESERVED_PYTHON_ROOT_FILES if (source_dir / file_name).exists()
    )
    if collisions:
        joined = ", ".join(collisions)
        raise ProfileConfigError(
            f"{config_path}: profiles.{profile_name}.python.source_dir contains reserved files: {joined}"
        )

    return PythonProfile(
        source_dir=source_dir,
        entry_module=entry_module,
        entry_function=entry_function,
    )


def _load_cpp_profile(
    *,
    profile_name: str,
    raw_cpp: dict[str, object],
    config_dir: Path,
    config_path: Path,
) -> CppProfile:
    """Load one C++ profile contract."""

    source_dir = _resolve_required_directory(
        raw_cpp.get("source_dir"),
        config_dir=config_dir,
        field_name=f"profiles.{profile_name}.cpp.source_dir",
        config_path=config_path,
    )

    raw_sources = raw_cpp.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ProfileConfigError(f"{config_path}: profiles.{profile_name}.cpp.sources must be a non-empty list")

    sources: list[Path] = []
    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, str) or not raw_source.strip():
            raise ProfileConfigError(
                f"{config_path}: profiles.{profile_name}.cpp.sources[{index}] must be a non-empty string"
            )
        source_path = (source_dir / raw_source).resolve()
        if not source_path.exists():
            raise ProfileConfigError(
                f"{config_path}: profiles.{profile_name}.cpp.sources[{index}] not found: {source_path}"
            )
        sources.append(source_path)

    output_uf2 = _resolve_path(
        raw_cpp.get("output_uf2"),
        config_dir=config_dir,
        field_name=f"profiles.{profile_name}.cpp.output_uf2",
        config_path=config_path,
    )

    return CppProfile(
        source_dir=source_dir,
        sources=tuple(sources),
        output_uf2=output_uf2,
    )


def _resolve_required_directory(
    raw_value: object,
    *,
    config_dir: Path,
    field_name: str,
    config_path: Path,
) -> Path:
    """Resolve and validate one required directory path."""

    path = _resolve_path(raw_value, config_dir=config_dir, field_name=field_name, config_path=config_path)
    if not path.exists():
        raise ProfileConfigError(f"{config_path}: {field_name} not found: {path}")
    if not path.is_dir():
        raise ProfileConfigError(f"{config_path}: {field_name} must be a directory: {path}")
    return path


def _resolve_existing_path(
    raw_value: object,
    *,
    default: Path,
    config_dir: Path,
    field_name: str,
    config_path: Path,
) -> Path:
    """Resolve one optional path and require it to exist."""

    if raw_value is None:
        resolved = default
    else:
        resolved = _resolve_path(raw_value, config_dir=config_dir, field_name=field_name, config_path=config_path)
    if not resolved.exists():
        raise ProfileConfigError(f"{config_path}: {field_name} not found: {resolved}")
    return resolved


def _resolve_path(
    raw_value: object,
    *,
    config_dir: Path,
    field_name: str,
    config_path: Path,
) -> Path:
    """Resolve one path-like string relative to the config file."""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ProfileConfigError(f"{config_path}: {field_name} must be a non-empty string path")
    path = Path(raw_value).expanduser()
    return path if path.is_absolute() else (config_dir / path).resolve()


def _optional_mapping(raw_value: object, section_name: str, config_path: Path) -> dict[str, object]:
    """Return one optional mapping section, defaulting to an empty mapping."""

    if raw_value is None:
        return {}
    return _require_mapping_in_parent(raw_value, section_name, config_path)


def _require_mapping(raw_config: dict[str, object], key: str, config_path: Path) -> dict[str, object]:
    """Require one named child mapping inside a parsed TOML document."""

    try:
        raw_value = raw_config[key]
    except KeyError as exc:
        raise ProfileConfigError(f"{config_path}: missing [{key}] section") from exc
    return _require_mapping_in_parent(raw_value, key, config_path)


def _require_mapping_in_parent(raw_value: object, section_name: str, config_path: Path) -> dict[str, object]:
    """Require one object to be a mapping."""

    if not isinstance(raw_value, dict):
        raise ProfileConfigError(f"{config_path}: {section_name} must be a table")
    return raw_value


def _require_string(
    raw_mapping: dict[str, object],
    key: str,
    field_name: str,
    config_path: Path,
) -> str:
    """Require one non-empty string value from a mapping."""

    try:
        raw_value = raw_mapping[key]
    except KeyError as exc:
        raise ProfileConfigError(f"{config_path}: missing {field_name}") from exc
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ProfileConfigError(f"{config_path}: {field_name} must be a non-empty string")
    return raw_value


def _optional_string(raw_value: object, default: str, field_name: str, config_path: Path) -> str:
    """Return an optional string or the provided default."""

    if raw_value is None:
        return default
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ProfileConfigError(f"{config_path}: {field_name} must be a non-empty string")
    return raw_value


def _optional_string_or_none(raw_value: object, field_name: str, config_path: Path) -> str | None:
    """Return an optional string or None."""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ProfileConfigError(f"{config_path}: {field_name} must be a non-empty string")
    return raw_value
