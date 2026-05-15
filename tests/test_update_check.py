"""Tests for the passive update notifier (`cli/_update_check.py`)."""
from __future__ import annotations

import datetime as _dt
import json
import sys

import pytest

from steam_manager.cli import _update_check as uc


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Redirect the notifier cache to a tmp file the test can inspect."""
    path = tmp_path / "update_check.json"
    monkeypatch.setenv("STEAM_MANAGER_UPDATE_STATE", str(path))
    return path


@pytest.fixture
def frozen_tty(monkeypatch):
    """Pretend we're a PyInstaller binary with a real stderr TTY.

    Patches the module-level _is_stderr_tty() instead of sys.stderr.isatty
    so we don't fight pytest's capsys (which rebinds sys.stderr per test).
    """
    monkeypatch.delenv("STEAM_MANAGER_NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(uc, "_is_stderr_tty", lambda: True)


# --- should_skip() --------------------------------------------------------


def test_should_skip_when_not_frozen(monkeypatch):
    monkeypatch.delenv("STEAM_MANAGER_NO_UPDATE_NOTIFIER", raising=False)
    # sys.frozen unset in dev mode → skip.
    assert uc.should_skip() is True


def test_should_skip_when_env_var_set(frozen_tty, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_NO_UPDATE_NOTIFIER", "1")
    assert uc.should_skip() is True


def test_should_skip_in_ci(frozen_tty, monkeypatch):
    monkeypatch.setenv("CI", "true")
    assert uc.should_skip() is True


def test_should_skip_when_stderr_not_tty(frozen_tty, monkeypatch):
    monkeypatch.setattr(uc, "_is_stderr_tty", lambda: False)
    assert uc.should_skip() is True


def test_should_not_skip_when_all_conditions_met(frozen_tty):
    assert uc.should_skip() is False


# --- cache I/O ------------------------------------------------------------


def test_save_then_load_cache_roundtrip(state_file):
    uc.save_cache("0.0.3", "https://example/h")
    cache = uc.load_cache()
    assert cache["latest_known"] == "0.0.3"
    assert cache["html_url"] == "https://example/h"
    assert "last_check_at" in cache


def test_load_cache_returns_none_when_missing(state_file):
    assert uc.load_cache() is None


def test_load_cache_returns_none_on_malformed_json(state_file):
    state_file.write_text("{not valid json")
    assert uc.load_cache() is None


def test_save_cache_is_atomic(state_file):
    uc.save_cache("0.0.3", "url1")
    uc.save_cache("0.0.4", "url2")
    # No partial files lying around.
    siblings = list(state_file.parent.iterdir())
    assert [p.name for p in siblings] == [state_file.name]
    assert uc.load_cache()["latest_known"] == "0.0.4"


# --- cache_is_fresh ---------------------------------------------------------


def test_cache_is_fresh_within_ttl():
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    assert uc.cache_is_fresh({"last_check_at": now}) is True


def test_cache_is_stale_past_ttl():
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=25)).isoformat()
    assert uc.cache_is_fresh({"last_check_at": old}) is False


def test_cache_is_stale_on_malformed_timestamp():
    assert uc.cache_is_fresh({"last_check_at": "not-a-date"}) is False
    assert uc.cache_is_fresh({}) is False


# --- run_post_command_hook ---------------------------------------------------


def test_hook_silent_when_skipped(state_file, capsys, monkeypatch):
    # Default: not frozen → skip.
    uc.run_post_command_hook("list")
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""


def test_hook_silent_when_invoked_command_is_update(
    frozen_tty, state_file, capsys
):
    # Pre-populate cache so we'd otherwise print.
    uc.save_cache("999.0.0", "https://example/h")
    uc.run_post_command_hook("update")
    assert capsys.readouterr().err == ""


def test_hook_prints_banner_when_newer_version_cached(
    frozen_tty, state_file, capsys
):
    uc.save_cache("999.0.0", "https://example/h")
    uc.run_post_command_hook("list")
    err = capsys.readouterr().err
    assert "A new release of steam-manager is available" in err
    assert "999.0.0" in err
    assert "https://example/h" in err


def test_hook_silent_when_on_latest(frozen_tty, state_file, capsys):
    # Use the actual current version so compare_versions returns 0.
    from steam_manager import __version__
    uc.save_cache(__version__, "https://example/h")
    uc.run_post_command_hook("list")
    assert capsys.readouterr().err == ""


def test_hook_refreshes_stale_cache(frozen_tty, state_file, fake_urlopen):
    # Pre-populate with a stale timestamp.
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)).isoformat()
    state_file.write_text(json.dumps({
        "last_check_at": old,
        "latest_known": "0.0.1",
        "html_url": "https://old/url",
    }))
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body={"tag_name": "v999.0.0", "html_url": "https://new/url"},
    )
    uc.run_post_command_hook("list")
    # Cache was refreshed.
    cache = uc.load_cache()
    assert cache["latest_known"] == "999.0.0"
    assert cache["html_url"] == "https://new/url"


def test_hook_never_raises_on_network_error(
    frozen_tty, state_file, fake_urlopen
):
    fake_urlopen.add_error(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        status=500,
    )
    # Must not raise — must return silently.
    uc.run_post_command_hook("list")


def test_hook_never_raises_on_internal_bug(
    frozen_tty, state_file, monkeypatch, capsys
):
    """If the hook itself has a bug, it must NOT leak to the user."""
    def broken(*a, **k):
        raise RuntimeError("internal notifier bug")
    monkeypatch.setattr(uc, "load_cache", broken)
    uc.run_post_command_hook("list")
    # The hook swallowed the exception.
    assert capsys.readouterr().err == ""
