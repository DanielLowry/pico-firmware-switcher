"""Backup creation and transfer helpers for switcher runtime state.

This module owns the lightweight backup workflow for the local SQLite event
database: parse a small TOML config, create a consistent snapshot, optionally
compress it, and hand it off to `rsync` over SSH.
"""

from __future__ import annotations

import gzip
import shutil
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore

from . import RUNTIME_ROOT

DEFAULT_BACKUP_CONFIG_PATH = RUNTIME_ROOT / "backup.toml"
DEFAULT_BACKUP_STAGING_DIR = RUNTIME_ROOT / "backups"
DEFAULT_BACKUP_COMPRESS = True
DEFAULT_REMOTE_PORT = 22
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10


class BackupConfigError(ValueError):
    """Raised when the backup configuration file is missing or invalid."""


class BackupTransferError(RuntimeError):
    """Raised when a backup artifact could not be transferred."""

    def __init__(self, message: str, *, staged_path: Path, remote_uri: str) -> None:
        super().__init__(message)
        self.staged_path = staged_path
        self.remote_uri = remote_uri


@dataclass(frozen=True)
class BackupRemoteConfig:
    """Remote destination details for off-host backups."""

    host: str
    user: str
    path: str
    ssh_key_path: Path
    ssh_port: int = DEFAULT_REMOTE_PORT
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS

    @property
    def remote_host(self) -> str:
        """Return the remote SSH host in `user@host` form."""

        return f"{self.user}@{self.host}"


@dataclass(frozen=True)
class BackupConfig:
    """Configuration used for creating and sending a database backup."""

    staging_dir: Path
    compress: bool
    remote: BackupRemoteConfig


@dataclass(frozen=True)
class BackupResult:
    """Metadata returned after a backup has been transferred."""

    file_name: str
    remote_uri: str
    size_bytes: int
    compressed: bool


def default_backup_config_path() -> Path:
    """Return the default config file path used by `backup-db`."""

    return DEFAULT_BACKUP_CONFIG_PATH


def load_backup_config(config_path: Path) -> BackupConfig:
    """Parse and validate the backup configuration file."""

    resolved_path = config_path.expanduser()
    if not resolved_path.exists():
        raise BackupConfigError(
            f"Backup config not found: {resolved_path}. "
            "Create it with [local] and [remote] sections."
        )

    with resolved_path.open("rb") as handle:
        raw_config = tomllib.load(handle)

    local_section = _require_mapping(raw_config, "local", resolved_path)
    remote_section = _require_mapping(raw_config, "remote", resolved_path)

    config_dir = resolved_path.parent
    staging_dir_value = local_section.get("staging_dir", str(DEFAULT_BACKUP_STAGING_DIR))
    compress_value = local_section.get("compress", DEFAULT_BACKUP_COMPRESS)

    host = _require_string(remote_section, "host", resolved_path)
    user = _require_string(remote_section, "user", resolved_path)
    remote_path = _require_string(remote_section, "path", resolved_path)
    ssh_key_value = _require_string(remote_section, "ssh_key_path", resolved_path)
    ssh_port = _optional_int(remote_section.get("port"), DEFAULT_REMOTE_PORT, "remote.port", resolved_path)
    connect_timeout = _optional_int(
        remote_section.get("connect_timeout_seconds"),
        DEFAULT_CONNECT_TIMEOUT_SECONDS,
        "remote.connect_timeout_seconds",
        resolved_path,
    )

    if not remote_path.startswith("/"):
        raise BackupConfigError(
            f"{resolved_path}: remote.path must be an absolute path, got {remote_path!r}"
        )

    ssh_key_path = _resolve_local_path(ssh_key_value, config_dir)
    if not ssh_key_path.exists():
        raise BackupConfigError(f"{resolved_path}: ssh key not found: {ssh_key_path}")

    if not isinstance(compress_value, bool):
        raise BackupConfigError(f"{resolved_path}: local.compress must be true or false")

    return BackupConfig(
        staging_dir=_resolve_local_path(str(staging_dir_value), config_dir),
        compress=compress_value,
        remote=BackupRemoteConfig(
            host=host,
            user=user,
            path=remote_path.rstrip("/"),
            ssh_key_path=ssh_key_path,
            ssh_port=ssh_port,
            connect_timeout_seconds=connect_timeout,
        ),
    )


def backup_database(*, db_path: Path, config: BackupConfig, verbose: bool = False) -> BackupResult:
    """Create a consistent SQLite snapshot and transfer it to the remote host."""

    staged_path = stage_backup_snapshot(
        db_path=db_path,
        staging_dir=config.staging_dir,
        compress=config.compress,
    )
    remote_uri = build_remote_uri(config.remote, staged_path.name)

    try:
        transfer_backup_artifact(
            artifact_path=staged_path,
            remote=config.remote,
            verbose=verbose,
        )
    except Exception as exc:
        raise BackupTransferError(
            str(exc),
            staged_path=staged_path,
            remote_uri=remote_uri,
        ) from exc

    size_bytes = staged_path.stat().st_size
    staged_path.unlink()
    return BackupResult(
        file_name=staged_path.name,
        remote_uri=remote_uri,
        size_bytes=size_bytes,
        compressed=config.compress,
    )


def stage_backup_snapshot(*, db_path: Path, staging_dir: Path, compress: bool) -> Path:
    """Create a local backup artifact and return its path."""

    resolved_db_path = db_path.expanduser()
    if not resolved_db_path.exists():
        raise FileNotFoundError(f"Database not found: {resolved_db_path}")

    resolved_staging_dir = staging_dir.expanduser()
    resolved_staging_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    plain_name = f"{resolved_db_path.stem}-{timestamp}.sqlite3"
    plain_path = resolved_staging_dir / plain_name
    temp_plain_path = resolved_staging_dir / f".{plain_name}.tmp"

    _sqlite_backup(source_path=resolved_db_path, destination_path=temp_plain_path)
    temp_plain_path.replace(plain_path)

    if not compress:
        return plain_path

    compressed_path = Path(f"{plain_path}.gz")
    temp_compressed_path = resolved_staging_dir / f".{compressed_path.name}.tmp"
    with plain_path.open("rb") as source_handle, gzip.open(temp_compressed_path, "wb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle)
    plain_path.unlink()
    temp_compressed_path.replace(compressed_path)
    return compressed_path


def transfer_backup_artifact(*, artifact_path: Path, remote: BackupRemoteConfig, verbose: bool = False) -> str:
    """Send a staged backup artifact to the configured remote host using rsync."""

    ssh_command = [
        "ssh",
        "-i",
        str(remote.ssh_key_path),
        "-p",
        str(remote.ssh_port),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        f"ConnectTimeout={remote.connect_timeout_seconds}",
    ]
    command = [
        "rsync",
        "-az",
        "--partial",
        "--protect-args",
        "-e",
        " ".join(shlex.quote(part) for part in ssh_command),
        str(artifact_path),
        _format_remote_target(remote=remote, file_name=artifact_path.name),
    ]
    if verbose:
        print("Running:", " ".join(shlex.quote(part) for part in command))
    subprocess.run(command, check=True)
    return build_remote_uri(remote, artifact_path.name)


def build_remote_uri(remote: BackupRemoteConfig, file_name: str) -> str:
    """Return the remote destination URI for one backup artifact."""

    return f"{remote.remote_host}:{remote.path}/{file_name}"


def _format_remote_target(*, remote: BackupRemoteConfig, file_name: str) -> str:
    """Format the remote rsync target."""

    remote_path = f"{remote.path}/{file_name}"
    return f"{remote.remote_host}:{remote_path}"


def _sqlite_backup(*, source_path: Path, destination_path: Path) -> None:
    """Create a consistent on-disk SQLite backup using the SQLite backup API."""

    source_uri = f"{source_path.resolve().as_uri()}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True)
    destination_connection = sqlite3.connect(destination_path)
    try:
        with destination_connection:
            source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def _require_mapping(config: dict[str, object], key: str, config_path: Path) -> dict[str, object]:
    """Return a required mapping section from parsed TOML."""

    value = config.get(key)
    if not isinstance(value, dict):
        raise BackupConfigError(f"{config_path}: missing [{key}] section")
    return value


def _require_string(config: dict[str, object], key: str, config_path: Path) -> str:
    """Return a required string value from one TOML section."""

    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BackupConfigError(f"{config_path}: missing or invalid {key!r} value")
    return value.strip()


def _optional_int(value: object, default: int, key: str, config_path: Path) -> int:
    """Return an optional integer with validation."""

    if value is None:
        return default
    if not isinstance(value, int):
        raise BackupConfigError(f"{config_path}: {key} must be an integer")
    return value


def _resolve_local_path(path_value: str, base_dir: Path) -> Path:
    """Resolve a local path string relative to the config file when needed."""

    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
