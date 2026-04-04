"""SQLite-backed event and snapshot logging for switcher operations.

This module encapsulates the optional persistence layer used by the CLI. It
defines the database schema, the small recorder abstraction used by commands,
and the formatting-friendly row shapes consumed by history and backup logic.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import RUNTIME_ROOT

try:
    from peewee import AutoField, Model, SqliteDatabase, TextField  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("peewee is required: pip install peewee") from exc


DB_PATH_ENV_VAR = "PICO_SWITCHER_DB"
DEFAULT_DB_PATH = RUNTIME_ROOT / "events.sqlite3"
DEFAULT_SNAPSHOT_SOURCE = "manual"
EVENT_FIELD_NAMES = (
    "created_at",
    "run_id",
    "source",
    "event_type",
    "status",
    "mode",
    "target_mode",
    "port",
    "mountpoint",
    "message",
    "details_json",
)
SNAPSHOT_FIELD_NAMES = (
    "created_at",
    "run_id",
    "source",
    "mode",
    "port",
    "message",
    "details_json",
)


def default_db_path() -> Path:
    """Return the configured database path."""

    configured = os.environ.get(DB_PATH_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DB_PATH


def _utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dumps(value: dict[str, Any]) -> str:
    """Serialize structured details into stable JSON."""

    return json.dumps(_to_jsonable(value), sort_keys=True)


def _to_jsonable(value: Any) -> Any:
    """Convert objects to JSON-safe primitives."""

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _build_models(database: SqliteDatabase) -> tuple[type[Model], type[Model]]:
    """Create model classes bound to one SQLite database instance."""

    db = database

    class BaseLogModel(Model):
        class Meta:
            database = db

    class EventLogModel(BaseLogModel):
        id = AutoField()
        created_at = TextField(index=True)
        run_id = TextField()
        source = TextField()
        event_type = TextField()
        status = TextField()
        mode = TextField(null=True)
        target_mode = TextField(null=True)
        port = TextField(null=True)
        mountpoint = TextField(null=True)
        message = TextField(null=True)
        details_json = TextField(default="{}")

        class Meta:
            table_name = "event_log"
            indexes = (
                (("event_type", "created_at"), False),
            )

    class StateSnapshotModel(BaseLogModel):
        id = AutoField()
        created_at = TextField(index=True)
        run_id = TextField()
        source = TextField()
        mode = TextField(null=True)
        port = TextField(null=True)
        message = TextField(null=True)
        details_json = TextField(default="{}")

        class Meta:
            table_name = "state_snapshot"

    return EventLogModel, StateSnapshotModel


class PicoLogStore:
    """Manage the SQLite database used for event and snapshot logging."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = SqliteDatabase(
            self.db_path,
            pragmas={
                "journal_mode": "wal",
                "synchronous": "normal",
            },
        )
        self._event_model, self._snapshot_model = _build_models(self._db)
        self._db.connect(reuse_if_open=True)
        self._db.create_tables([self._event_model, self._snapshot_model], safe=True)

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        if not self._db.is_closed():
            self._db.close()

    def log_event(
        self,
        *,
        run_id: str,
        source: str,
        event_type: str,
        status: str,
        mode: Optional[str] = None,
        target_mode: Optional[str] = None,
        port: Optional[str] = None,
        mountpoint: Optional[str] = None,
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Persist a single event row."""

        self._event_model.create(
            created_at=_utc_now(),
            run_id=run_id,
            source=source,
            event_type=event_type,
            status=status,
            mode=mode,
            target_mode=target_mode,
            port=port,
            mountpoint=mountpoint,
            message=message,
            details_json=_json_dumps(details or {}),
        )

    def log_snapshot(
        self,
        *,
        run_id: str,
        source: str,
        mode: Optional[str],
        port: Optional[str],
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Persist a state snapshot row."""

        self._snapshot_model.create(
            created_at=_utc_now(),
            run_id=run_id,
            source=source,
            mode=mode,
            port=port,
            message=message,
            details_json=_json_dumps(details or {}),
        )

    def fetch_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return recent event rows as dictionaries."""

        query = self._event_model.select().order_by(self._event_model.id.desc())
        if limit is not None:
            query = query.limit(limit)
        return [_decode_model(model, EVENT_FIELD_NAMES) for model in query]

    def fetch_snapshots(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return recent state snapshot rows as dictionaries."""

        query = self._snapshot_model.select().order_by(self._snapshot_model.id.desc())
        if limit is not None:
            query = query.limit(limit)
        return [_decode_model(model, SNAPSHOT_FIELD_NAMES) for model in query]


def _decode_model(model: Model, field_names: tuple[str, ...]) -> dict[str, Any]:
    """Convert a Peewee model instance to the dict shape used by the CLI."""

    data = {field_name: getattr(model, field_name) for field_name in field_names}
    data["details"] = json.loads(data.pop("details_json"))
    return data


@dataclass
class EventRecorder:
    """Attach command-scoped metadata to database writes."""

    store: Optional[PicoLogStore]
    source: str
    verbose: bool = False
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def event(
        self,
        event_type: str,
        *,
        status: str = "ok",
        mode: Optional[str] = None,
        target_mode: Optional[str] = None,
        port: Optional[str] = None,
        mountpoint: Optional[str] = None,
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record a command event when persistence is enabled."""

        if self.store is None:
            return
        self.store.log_event(
            run_id=self.run_id,
            source=self.source,
            event_type=event_type,
            status=status,
            mode=mode,
            target_mode=target_mode,
            port=port,
            mountpoint=mountpoint,
            message=message,
            details=details,
        )

    def snapshot(
        self,
        *,
        mode: Optional[str],
        port: Optional[str],
        message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        source: Optional[str] = None,
    ) -> None:
        """Record a state snapshot when persistence is enabled."""

        if self.store is None:
            return
        self.store.log_snapshot(
            run_id=self.run_id,
            source=source or self.source,
            mode=mode,
            port=port,
            message=message,
            details=details,
        )

    def close(self) -> None:
        """Close the underlying store when one is attached."""

        if self.store is not None:
            self.store.close()


def create_event_recorder(
    *,
    source: str,
    db_path: Path,
    verbose: bool,
    required: bool = False,
) -> EventRecorder:
    """Create a recorder, optionally degrading gracefully when unavailable."""

    try:
        store = PicoLogStore(db_path)
    except Exception as exc:
        if required:
            raise
        if verbose:
            print(f"Warning: logging disabled: {exc}", file=sys.stderr)
        return EventRecorder(store=None, source=source, verbose=verbose)
    return EventRecorder(store=store, source=source, verbose=verbose)
