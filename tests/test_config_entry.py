"""Tests for `cli/_config_entry.py` — the config UI dispatcher.

Fast lane: no Textual import (the tui package's `run` is patched without ever
constructing the App), no asyncio. Covers the non-TTY guard, the
flag/env/default precedence, and the mutually-exclusive flags.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from steam_manager import cli

runner = CliRunner()


@pytest.fixture
def user_policy(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "user.toml"
    monkeypatch.setenv("STEAM_MANAGER_USER_POLICY", str(p))
    monkeypatch.delenv("STEAM_MANAGER_CONFIG_UI", raising=False)
    return p


@pytest.fixture
def interactive(monkeypatch):
    """Force the TTY check True so the guard lets the dispatcher route."""
    monkeypatch.setattr(
        "steam_manager.cli._config_entry._ui_is_interactive", lambda: True)


@pytest.fixture
def spies(monkeypatch) -> dict:
    """Replace both front-end entry points with counters (no UI ever runs)."""
    calls = {"classic": 0, "tui": 0}
    monkeypatch.setattr("steam_manager.cli._wizard.run",
                        lambda: calls.__setitem__("classic", calls["classic"] + 1))
    monkeypatch.setattr("steam_manager.cli.tui.run",
                        lambda: calls.__setitem__("tui", calls["tui"] + 1))
    return calls


def test_non_tty_exits_2_with_hint(user_policy, spies):
    result = runner.invoke(cli.app, ["config"])
    assert result.exit_code == 2
    assert "config get" in result.output
    assert "config path" in result.output
    assert spies == {"classic": 0, "tui": 0}


def test_default_routes_tui_when_interactive(user_policy, interactive, spies):
    result = runner.invoke(cli.app, ["config"])
    assert result.exit_code == 0
    assert spies == {"classic": 0, "tui": 1}


def test_tui_flag_routes_tui(user_policy, interactive, spies):
    result = runner.invoke(cli.app, ["config", "--tui"])
    assert result.exit_code == 0
    assert spies == {"classic": 0, "tui": 1}


def test_classic_flag_routes_classic(user_policy, interactive, spies):
    result = runner.invoke(cli.app, ["config", "--classic"])
    assert result.exit_code == 0
    assert spies == {"classic": 1, "tui": 0}


def test_env_tui_routes_tui(user_policy, interactive, spies, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_CONFIG_UI", "tui")
    runner.invoke(cli.app, ["config"])
    assert spies == {"classic": 0, "tui": 1}


def test_env_classic_routes_classic(user_policy, interactive, spies, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_CONFIG_UI", "classic")
    runner.invoke(cli.app, ["config"])
    assert spies == {"classic": 1, "tui": 0}


def test_env_unrecognized_falls_back_to_default(user_policy, interactive, spies, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_CONFIG_UI", "banana")
    runner.invoke(cli.app, ["config"])
    assert spies == {"classic": 0, "tui": 1}  # default is tui


def test_flag_beats_env(user_policy, interactive, spies, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_CONFIG_UI", "classic")
    runner.invoke(cli.app, ["config", "--tui"])
    assert spies == {"classic": 0, "tui": 1}


def test_classic_and_tui_conflict_exits_2(user_policy, interactive, spies):
    result = runner.invoke(cli.app, ["config", "--classic", "--tui"])
    assert result.exit_code == 2
    assert spies == {"classic": 0, "tui": 0}


def test_wizard_subcommand_routes_tui(user_policy, interactive, spies):
    result = runner.invoke(cli.app, ["config", "wizard", "--tui"])
    assert result.exit_code == 0
    assert spies == {"classic": 0, "tui": 1}
