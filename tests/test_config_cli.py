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
    return p


def test_config_path_prints_override(user_policy):
    result = runner.invoke(cli.app, ["config", "path"])
    assert result.exit_code == 0
    assert str(user_policy) in result.stdout


def test_config_set_writes_value(user_policy):
    result = runner.invoke(cli.app, ["config", "set", "games.compat_tool", "Proton-9.0"])
    assert result.exit_code == 0
    text = user_policy.read_text()
    assert 'compat_tool = "Proton-9.0"' in text


def test_config_set_preserves_user_comments(user_policy):
    user_policy.write_text(
        "# This is my custom comment\n"
        "[games]\n"
        'compat_tool = "Old"\n'
    )
    result = runner.invoke(cli.app, ["config", "set", "games.compat_tool", "New"])
    assert result.exit_code == 0
    text = user_policy.read_text()
    assert "# This is my custom comment" in text
    assert 'compat_tool = "New"' in text


def test_config_set_type_inference(user_policy):
    runner.invoke(cli.app, ["config", "set", "general.max_backups", "42"])
    runner.invoke(cli.app, ["config", "set", "overrides.111.ignore", "true"])
    text = user_policy.read_text()
    assert "max_backups = 42" in text         # int, not "42"
    assert "ignore = true" in text             # bool, not "true"


def test_config_get_prints_user_override(user_policy):
    user_policy.write_text('[games]\ncompat_tool = "Proton-9.0"\n')
    result = runner.invoke(cli.app, ["config", "get", "games.compat_tool"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "Proton-9.0"


def test_config_get_falls_back_to_factory_when_no_user_override(user_policy, monkeypatch):
    # User file empty / absent → get must still return the factory value.
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    result = runner.invoke(cli.app, ["config", "get", "games.launch_options"])
    assert result.exit_code == 0
    assert "scopebuddy -- %command%" in result.stdout


def test_config_get_missing_key_exits_3(user_policy):
    result = runner.invoke(cli.app, ["config", "get", "does.not.exist"])
    assert result.exit_code == 3


def test_config_unset_drops_empty_parent_table(user_policy):
    user_policy.write_text("[overrides.111]\nignore = true\n")
    result = runner.invoke(cli.app, ["config", "unset", "overrides.111.ignore"])
    assert result.exit_code == 0
    text = user_policy.read_text()
    assert "[overrides.111]" not in text       # whole table dropped
    assert "ignore" not in text


def test_config_unset_missing_key_exits_3(user_policy):
    result = runner.invoke(cli.app, ["config", "unset", "games.compat_tool"])
    assert result.exit_code == 3


def test_config_no_subcommand_launches_classic_wizard(user_policy, monkeypatch):
    """`steam-manager config --classic` opens the classic questionary wizard.

    The TTY check is forced True because CliRunner's captured streams report
    isatty() == False (which would otherwise route to the non-TTY hint)."""
    called = {"n": 0}
    monkeypatch.setattr("steam_manager.cli._config_entry._ui_is_interactive", lambda: True)
    monkeypatch.setattr("steam_manager.cli._wizard.run", lambda: called.__setitem__("n", called["n"] + 1))
    result = runner.invoke(cli.app, ["config", "--classic"])
    assert result.exit_code == 0
    assert called["n"] == 1


def test_config_wizard_explicit_launches_classic_wizard(user_policy, monkeypatch):
    """`steam-manager config wizard --classic` is the explicit classic form."""
    called = {"n": 0}
    monkeypatch.setattr("steam_manager.cli._config_entry._ui_is_interactive", lambda: True)
    monkeypatch.setattr("steam_manager.cli._wizard.run", lambda: called.__setitem__("n", called["n"] + 1))
    result = runner.invoke(cli.app, ["config", "wizard", "--classic"])
    assert result.exit_code == 0
    assert called["n"] == 1
