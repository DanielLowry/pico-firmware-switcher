"""History command and compact terminal formatting helpers.

This module keeps the log/snapshot history output isolated from parser and
command execution code. The intent is to make formatting changes cheap while
keeping the rest of the CLI focused on command orchestration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import PROJECT_ROOT
from ..pico_log import PicoLogStore
from .utils import expand_path


def run_history(args: Any) -> int:
    """Handle the history reporting command."""

    store = PicoLogStore(expand_path(args.db_path))
    try:
        if args.kind in {"all", "events"}:
            print_history_section(
                "Events",
                store.fetch_events(limit=args.limit),
                event_rows=True,
                full_details=args.full_details,
            )
        if args.kind in {"all", "snapshots"}:
            if args.kind == "all":
                print()
            print_history_section(
                "Snapshots",
                store.fetch_snapshots(limit=args.limit),
                event_rows=False,
                full_details=args.full_details,
            )
    finally:
        store.close()
    return 0


def print_history_section(
    title: str,
    rows: list[dict[str, object]],
    event_rows: bool,
    *,
    full_details: bool = False,
) -> None:
    """Print one history section in a compact single-line-per-row format."""

    print(title)
    if not rows:
        print("  none")
        return

    for row in rows:
        details = row.get("details")
        detail_parts = _format_history_details(
            details=details,
            event_type=str(row.get("event_type")) if event_rows else None,
            full_details=full_details,
        )
        parts = [_format_history_timestamp(str(row["created_at"]))]
        if event_rows:
            parts.extend(
                [
                    str(row["status"]),
                    str(row["event_type"]),
                    f"source={row['source']}",
                ]
            )
            if row.get("mode"):
                parts.append(f"mode={row['mode']}")
            if row.get("target_mode"):
                parts.append(f"target={row['target_mode']}")
            if row.get("mountpoint"):
                parts.append(f"mount={row['mountpoint']}")
        else:
            parts.extend(
                [
                    "snapshot",
                    f"source={row['source']}",
                    f"mode={row.get('mode') or 'unknown'}",
                ]
            )
        if row.get("port"):
            parts.append(f"port={row['port']}")
        if _should_include_history_message(row=row, detail_parts=detail_parts, full_details=full_details):
            parts.append(f"message={row['message']}")
        parts.extend(detail_parts)
        print("  " + " | ".join(parts))


_DETAIL_LABELS = {
    "command": "cmd",
    "config_path": "cfg",
    "db_path": "db",
    "file_name": "file",
    "force_flash": "force",
    "helper_files": "files",
    "interval": "every",
    "mount_base": "base",
    "entry_function": "entry_fn",
    "entry_module": "entry_mod",
    "entry_symbol": "entry",
    "reason": "reason",
    "profile": "profile",
    "remote_host": "host",
    "remote_path": "dest",
    "remote_uri": "remote",
    "requested_port": "req",
    "service_name": "service",
    "size_bytes": "size",
    "source_dir": "src",
    "sources": "files",
    "staged_path": "staged",
    "status": "status",
    "uf2_path": "uf2",
    "unit_dir": "units",
    "runtime_files": "runtime",
    "build_dir": "build",
    "bootsel_command": "bootsel",
}

_DETAIL_PRIORITY = {
    "file_name": 0,
    "config_path": 1,
    "db_path": 2,
    "remote_host": 3,
    "remote_path": 4,
    "remote_uri": 5,
    "staged_path": 6,
    "service_name": 7,
    "interval": 8,
    "uf2_path": 9,
    "helper_files": 10,
    "profile": 11,
    "source_dir": 12,
    "entry_module": 13,
    "entry_function": 14,
    "entry_symbol": 15,
    "runtime_files": 16,
    "sources": 17,
    "build_dir": 18,
    "bootsel_command": 19,
    "reason": 20,
    "status": 21,
    "requested_port": 22,
    "force_flash": 23,
    "command": 24,
    "unit_dir": 25,
    "mount_base": 26,
}


def _format_history_details(
    *,
    details: object,
    event_type: str | None,
    full_details: bool,
) -> list[str]:
    """Return compact or raw detail fragments for one history row."""

    if not details:
        return []
    if full_details:
        return [f"details={json.dumps(details, sort_keys=True)}"]
    if not isinstance(details, dict):
        return [f"details={_truncate_text(str(details), 120)}"]

    rendered_items: list[str] = []
    for key, value in sorted(details.items(), key=lambda item: (_DETAIL_PRIORITY.get(item[0], 99), item[0])):
        rendered = _render_history_detail_item(key, value)
        if rendered:
            rendered_items.append(rendered)

    if not rendered_items:
        return []

    preferred_limit = 4 if event_type != "backup_transfer" else 5
    if len(rendered_items) <= preferred_limit:
        return rendered_items
    omitted_count = len(rendered_items) - preferred_limit
    return rendered_items[:preferred_limit] + [f"+{omitted_count} more"]


def _render_history_detail_item(key: str, value: object) -> str | None:
    """Render one detail entry in a compact human-readable form."""

    if value is None:
        return None
    label = _DETAIL_LABELS.get(key, key)
    rendered_value = _render_history_detail_value(key, value)
    if rendered_value == "":
        return None
    return f"{label}={rendered_value}"


def _render_history_detail_value(key: str, value: object) -> str:
    """Render one detail value in a compact human-readable form."""

    if key == "remote_uri" and isinstance(value, str):
        return _short_remote_uri(value)
    if key in {"config_path", "db_path", "staged_path", "uf2_path", "unit_dir", "mount_base"} and isinstance(value, str):
        return _short_path(value)
    if key == "remote_path" and isinstance(value, str):
        return _short_path(value, tail_segments=1)
    if key == "helper_files" and isinstance(value, list):
        return _render_history_list(value, treat_as_path=True)
    if key == "size_bytes" and isinstance(value, int):
        return f"{value}B"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return _render_history_list(value)
    return _truncate_text(str(value), 80)


def _render_history_list(values: list[Any], *, treat_as_path: bool = False) -> str:
    """Render a list value compactly for history output."""

    items: list[str] = []
    for value in values:
        text = str(value)
        items.append(_short_path(text) if treat_as_path else _truncate_text(text, 32))

    if len(items) <= 2:
        return ",".join(items)
    return ",".join(items[:2]) + f",+{len(items) - 2}"


def _short_remote_uri(remote_uri: str) -> str:
    """Compact a remote URI to host plus a short tail path."""

    host, separator, path = remote_uri.partition(":")
    if not separator:
        return _truncate_text(remote_uri, 80)
    return f"{host}:{_short_path(path, tail_segments=2)}"


def _short_path(path_value: str, *, tail_segments: int = 1) -> str:
    """Compact a filesystem path for terminal display."""

    path = Path(path_value).expanduser()
    if path.is_absolute():
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            parts = list(path.parts)
            if parts and parts[0] == path.anchor:
                parts = parts[1:]
            if len(parts) >= tail_segments:
                return "/".join(parts[-tail_segments:])
            if path.name:
                return path.name
    return _truncate_text(path_value, 80)


def _format_history_timestamp(value: str) -> str:
    """Normalize history timestamps for compact output."""

    return value.replace("+00:00", "Z")


def _truncate_text(value: str, limit: int) -> str:
    """Trim long strings so single-line history stays readable."""

    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _should_include_history_message(
    *,
    row: dict[str, object],
    detail_parts: list[str],
    full_details: bool,
) -> bool:
    """Decide whether to print the free-form message for one row."""

    if not row.get("message"):
        return False
    if full_details:
        return True
    return row.get("status") == "error" or not detail_parts
