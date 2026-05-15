"""Passive update notifier — gh-cli style, 24h-cached, stderr-only.

Fired from the Click result_callback at the end of every command (see
`cli/__init__.py:main()`). The hook reads a small JSON cache; if stale,
it performs a single GitHub API call with a tight 2s timeout, swallows
every possible error, and writes a banner to stderr only if a newer
version exists.

Skipped wholesale in any "non-interactive" context: piped stderr, CI,
dev mode (not frozen), the `update` command itself, or when the user
sets STEAM_MANAGER_NO_UPDATE_NOTIFIER. The banner must NEVER break a
user's command — every entry point is wrapped in broad try/except.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

from steam_manager import __version__
from steam_manager.cli._common import update_state_path
from steam_manager.io import github_releases

_TTL_HOURS = 24
_FETCH_TIMEOUT = 2.0


def _is_stderr_tty() -> bool:
    """Indirection layer so tests can monkey-patch the TTY check on the
    module rather than fight pytest's `capsys` (which rebinds sys.stderr)."""
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def should_skip() -> bool:
    """Bail out fast in any non-interactive or opt-out context."""
    if not getattr(sys, "frozen", False):
        # Dev mode: a "new version available" banner would point to the
        # PyInstaller release, which doesn't match a pip/editable install.
        return True
    if not _is_stderr_tty():
        return True
    if os.environ.get("STEAM_MANAGER_NO_UPDATE_NOTIFIER"):
        return True
    if os.environ.get("CI"):
        return True
    return False


def load_cache() -> dict | None:
    """Return the cached state, or None on any read/parse error."""
    try:
        return json.loads(update_state_path().read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def save_cache(latest_version: str, html_url: str) -> None:
    """Atomic write: tempfile in same dir + os.replace.

    Failures (read-only fs, permission denied) are swallowed by the caller.
    """
    path = update_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_check_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "latest_known": latest_version,
        "html_url": html_url,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)


def cache_is_fresh(cache: dict, *, ttl_hours: int = _TTL_HOURS) -> bool:
    """True if the cache was written within ttl_hours."""
    try:
        ts = _dt.datetime.fromisoformat(cache["last_check_at"])
    except (KeyError, ValueError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    age = _dt.datetime.now(_dt.timezone.utc) - ts
    return age < _dt.timedelta(hours=ttl_hours)


def _refresh_cache_silently() -> dict | None:
    """Best-effort fetch + cache update. Returns the new cache or None on failure."""
    try:
        release = github_releases.fetch_latest_release(timeout=_FETCH_TIMEOUT)
    except Exception:
        return None
    try:
        save_cache(release.version, release.html_url)
    except OSError:
        # Cache write failed (read-only fs?). We can still print the banner
        # this once based on the in-memory data.
        pass
    return {
        "last_check_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "latest_known": release.version,
        "html_url": release.html_url,
    }


def _print_banner(latest_known: str, html_url: str) -> None:
    """gh-style 3-line banner on stderr."""
    sys.stderr.write(
        f"\nA new release of steam-manager is available: "
        f"{__version__} → {latest_known}\n"
        f"To upgrade, run: steam-manager update\n"
        f"{html_url}\n"
    )


def run_post_command_hook(invoked_command: str | None) -> None:
    """Entry point from cli.__init__.main()'s result_callback.

    Guarded with a broad try/except so a notifier bug NEVER breaks the
    user's command. `invoked_command` is the parsed sub-command name
    from sys.argv (best-effort).
    """
    try:
        if should_skip():
            return
        if invoked_command == "update":
            # Just updated; don't spam.
            return

        cache = load_cache()
        if cache is None or not cache_is_fresh(cache):
            cache = _refresh_cache_silently()
            if cache is None:
                return

        latest = cache.get("latest_known")
        html_url = cache.get("html_url", "")
        if not latest:
            return
        if github_releases.compare_versions(__version__, latest) < 0:
            _print_banner(latest, html_url)
    except Exception:
        # The notifier must never raise. Swallow anything.
        return
