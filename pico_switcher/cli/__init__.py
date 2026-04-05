"""CLI package for the Pico switcher.

This package holds the refactored command-line implementation behind the thin
public facade in `pico_switcher.pico_cli`. The split is intentionally shallow:
parser construction, command handlers, history rendering, and CLI bootstrap are
separated, but the underlying service modules still own the real behavior.
"""
