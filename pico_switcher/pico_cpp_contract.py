"""Shared managed C++ contract constants.

This module defines the small public contract shared by the host tooling and
the managed C++ runtime. Keeping these identifiers in one place makes the
client interface explicit: host code knows which serial command to send and
build/runtime code agree on the one client symbol that must be provided.
"""

from __future__ import annotations


CPP_RUNTIME_BANNER = "FW:CPP"
CPP_PROFILE_BANNER_PREFIX = "PROFILE:CPP:"
CPP_BOOTSEL_COMMAND = "BOOTSEL"
CPP_CLIENT_ENTRY_SYMBOL = "client_app_main"
CPP_CLIENT_HEADER_NAME = "switcher_client.h"
