"""Safety: detect whether the Steam client is currently running.

The presence of a live `~/.steam/steam.pid` blocks every destructive
operation (`apply`, `clear`, `restore`, `shortcuts edit`) unless --force
is passed. Steam keeps configs in memory and rewrites them at exit, so
edits made while Steam is running get clobbered on shutdown.
"""
from __future__ import annotations

import os
from pathlib import Path

_STEAM_PID_FILE = Path.home() / ".steam" / "steam.pid"


def steam_running() -> int | None:
    """Return Steam's PID if alive, else None."""
    if not _STEAM_PID_FILE.exists():
        return None
    try:
        pid = int(_STEAM_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except PermissionError:
        # The process exists but belongs to another user — still running.
        return pid
    except (ProcessLookupError, OSError):
        return None
    return pid
