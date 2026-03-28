"""Helpers for generating and installing a periodic state snapshot timer."""

from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import PROJECT_ROOT


DEFAULT_UNIT_DIR = Path("~/.config/systemd/user")
DEFAULT_SERVICE_NAME = "pico-switcher-state"
DEFAULT_TIMER_INTERVAL = "5min"


@dataclass(frozen=True)
class InstalledUnits:
    """Paths of the generated systemd unit files."""

    service_path: Path
    timer_path: Path


def render_state_service(
    *,
    repo_root: Path,
    python_executable: Path,
    db_path: Path,
    port: str,
    timeout: float,
) -> str:
    """Build the systemd service unit used for snapshot logging."""

    command = [
        str(python_executable),
        str(repo_root / "pico.py"),
        "log-state",
        "--port",
        port,
        "--timeout",
        str(timeout),
        "--source",
        "timer",
        "--db-path",
        str(db_path),
    ]
    exec_start = " ".join(shlex.quote(part) for part in command)
    return "\n".join(
        (
            "[Unit]",
            "Description=Log Raspberry Pi Pico firmware state snapshot",
            "",
            "[Service]",
            "Type=oneshot",
            f"WorkingDirectory={repo_root}",
            f"ExecStart={exec_start}",
            "",
        )
    )


def render_state_timer(*, service_name: str, interval: str) -> str:
    """Build the timer unit that invokes the state logging service."""

    return "\n".join(
        (
            "[Unit]",
            "Description=Record Raspberry Pi Pico firmware state on a timer",
            "",
            "[Timer]",
            "OnBootSec=2min",
            f"OnUnitActiveSec={interval}",
            "AccuracySec=30s",
            "Persistent=true",
            f"Unit={service_name}.service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        )
    )


def install_state_timer(
    *,
    repo_root: Path | None = None,
    python_executable: Path | None = None,
    db_path: Path,
    port: str,
    timeout: float,
    unit_dir: Path,
    service_name: str,
    interval: str,
) -> InstalledUnits:
    """Write user unit files for periodic state logging."""

    resolved_repo_root = repo_root or PROJECT_ROOT
    resolved_python = python_executable or Path(sys.executable).resolve()
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path = unit_dir / f"{service_name}.service"
    timer_path = unit_dir / f"{service_name}.timer"

    service_path.write_text(
        render_state_service(
            repo_root=resolved_repo_root,
            python_executable=resolved_python,
            db_path=db_path,
            port=port,
            timeout=timeout,
        ),
        encoding="utf-8",
    )
    timer_path.write_text(
        render_state_timer(service_name=service_name, interval=interval),
        encoding="utf-8",
    )
    return InstalledUnits(service_path=service_path, timer_path=timer_path)


def enable_state_timer(service_name: str) -> None:
    """Reload systemd user units and enable the snapshot timer."""

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{service_name}.timer"], check=True)
