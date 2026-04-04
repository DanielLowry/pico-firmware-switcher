"""Shared package constants for the Pico firmware switcher.

This module centralizes the repository root and runtime data locations so the
CLI, logging, config, and helper modules can resolve paths consistently without
re-deriving repo layout details in multiple places.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = PROJECT_ROOT / ".pico-switcher"
