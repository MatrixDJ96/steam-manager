"""Shared CLI helpers: exit codes, path resolution, env-var overrides.

This module is the project-internal counterpart to pipx's
`commands/common.py` — utilities used by multiple commands and sub-typers,
but not by io/ (which must not depend on the CLI layer).

Env-var overrides honored here are documented in `docs/REFERENCE.md` and
in `AGENTS.md` (Tests section). Tests rely on them to redirect filesystem
side effects into `tmp_path`.
"""
from __future__ import annotations

import datetime as _dt
import os
from enum import IntEnum
from importlib.resources import files
from pathlib import Path

from steam_manager.io.policies_toml import user_path as _user_path


class ExitCode(IntEnum):
    OK = 0
    DRIFT = 1
    STEAM_RUNNING = 2
    PARSE_ERROR = 3
    WRITE_ERROR = 4


USER_POLICY_PATH = Path.home() / ".config" / "steam-manager" / "policies.toml"


def steam_root() -> Path | None:
    """Honor STEAM_MANAGER_STEAM_ROOT (used by tests + advanced users)."""
    override = os.environ.get("STEAM_MANAGER_STEAM_ROOT")
    return Path(override) if override else None


def config_ui_mode() -> str | None:
    """Honor STEAM_MANAGER_CONFIG_UI = tui|classic (used by tests + users).

    An unrecognized value returns None so the built-in default still applies —
    an env typo never silently picks a UI.
    """
    val = (os.environ.get("STEAM_MANAGER_CONFIG_UI") or "").strip().lower()
    return val if val in ("tui", "classic") else None


def policy_paths() -> list[Path]:
    """Resolve the layered policy paths: factory + user override.

    STEAM_MANAGER_POLICY_PATHS (colon-separated) overrides both for tests.
    Falls back to the env-aware `policies_toml.user_path()` so a test that
    redirects only the user file via STEAM_MANAGER_USER_POLICY still sees
    the redirect through this helper.
    """
    override = os.environ.get("STEAM_MANAGER_POLICY_PATHS")
    if override:
        return [Path(p) for p in override.split(":") if p]
    factory = Path(str(files("steam_manager").joinpath("policies.toml")))
    return [factory, _user_path()]


def backup_root() -> Path:
    """Honor STEAM_MANAGER_BACKUP_ROOT (used by tests)."""
    override = os.environ.get("STEAM_MANAGER_BACKUP_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "steam-manager" / "backups"


def iso_timestamp() -> str:
    """Filesystem-safe ISO-8601 timestamp used in checkpoint archive names."""
    return _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def update_state_path() -> Path:
    """Honor STEAM_MANAGER_UPDATE_STATE (used by tests).

    Holds the 24h-cached `{last_check_at, latest_known, html_url}` for the
    passive update notifier. Sibling of backup_root() under XDG state.
    """
    override = os.environ.get("STEAM_MANAGER_UPDATE_STATE")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "steam-manager" / "update_check.json"
