"""SQLite-backed event and state logging for Pico switcher operations."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


DB_PATH_ENV_VAR = "PICO_SWITCHER_DB"
DEFAULT_DB_PATH = Path.home() / ".local" / "state" / "pico-firmware-switcher" / "events.sqlite3"
DEFAULT_HISTORY_LIMIT = 20
DEFAULT_SNAPSHOT_SOURCE = "manual"


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


class PicoLogStore:
    """Manage the SQLite database used for event and snapshot logging."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self._conn.close()

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they do not exist yet."""

        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                mode TEXT,
                target_mode TEXT,
                port TEXT,
                mountpoint TEXT,
                message TEXT,
                details_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_event_log_created_at
                ON event_log(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_event_log_type_created_at
                ON event_log(event_type, created_at DESC);

            CREATE TABLE IF NOT EXISTS state_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                mode TEXT,
                port TEXT,
                message TEXT,
                details_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_state_snapshot_created_at
                ON state_snapshot(created_at DESC);
            """
        )
        self._conn.commit()

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

        self._conn.execute(
            """
            INSERT INTO event_log (
                created_at, run_id, source, event_type, status, mode, target_mode,
                port, mountpoint, message, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                run_id,
                source,
                event_type,
                status,
                mode,
                target_mode,
                port,
                mountpoint,
                message,
                _json_dumps(details or {}),
            ),
        )
        self._conn.commit()

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

        self._conn.execute(
            """
            INSERT INTO state_snapshot (
                created_at, run_id, source, mode, port, message, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                run_id,
                source,
                mode,
                port,
                message,
                _json_dumps(details or {}),
            ),
        )
        self._conn.commit()

    def fetch_events(self, limit: int) -> list[dict[str, Any]]:
        """Return recent event rows as dictionaries."""

        rows = self._conn.execute(
            """
            SELECT created_at, run_id, source, event_type, status, mode, target_mode,
                   port, mountpoint, message, details_json
            FROM event_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_decode_row(row) for row in rows]

    def fetch_snapshots(self, limit: int) -> list[dict[str, Any]]:
        """Return recent state snapshot rows as dictionaries."""

        rows = self._conn.execute(
            """
            SELECT created_at, run_id, source, mode, port, message, details_json
            FROM state_snapshot
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_decode_row(row) for row in rows]


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite row to a dict and decode its JSON payload."""

    data = dict(row)
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
