"""Steam-running guard: refuse to write while Steam is alive.

Steam keeps `config.vdf`, `localconfig.vdf`, and `shortcuts.vdf` in memory
and rewrites them when the client exits. Any edit made by us while Steam
is running would be clobbered. The guard is honored by `apply`, `clear`,
`restore`, and `shortcuts edit`; `--force` (or STEAM_MANAGER_FORCE=1)
bypasses it for advanced use.
"""
from __future__ import annotations

import os

import typer

from steam_manager import render, safety
from steam_manager.cli._common import ExitCode


def check_steam_closed(force: bool) -> None:
    """Exit with STEAM_RUNNING if Steam is alive and force is not set."""
    if force or os.environ.get("STEAM_MANAGER_FORCE") == "1":
        return
    pid = safety.steam_running()
    if pid:
        render.error(
            f"Steam is running (PID {pid}). Close Steam and retry, or use --force."
        )
        raise typer.Exit(ExitCode.STEAM_RUNNING)
