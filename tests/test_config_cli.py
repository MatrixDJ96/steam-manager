from __future__ import annotations

import os
import stat
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


def test_config_path_prints_override(user_policy, capsys):
    result = runner.invoke(cli.app, ["config", "path"])
    assert result.exit_code == 0
    assert str(user_policy) in result.stdout


def test_config_show_prints_effective_merged_config(user_policy, monkeypatch):
    # No user file → show still prints the factory defaults (merged).
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0
    assert "[games]" in result.stdout
    assert "compat_tool" in result.stdout


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
    # User file empty / absent → get must still return the factory value,
    # since `get` queries the merged config (same source of truth as `show`).
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    result = runner.invoke(cli.app, ["config", "get", "games.compat_tool"])
    assert result.exit_code == 0
    assert "Proton-CachyOS Latest" in result.stdout


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


def test_config_reset_seeds_template_when_absent(user_policy):
    result = runner.invoke(cli.app, ["config", "reset", "--yes"])
    assert result.exit_code == 0
    assert user_policy.exists()
    assert "# [games]" in user_policy.read_text()


def test_config_reset_overwrites_existing_with_yes(user_policy):
    user_policy.write_text('[games]\ncompat_tool = "Proton-9.0"\n')
    result = runner.invoke(cli.app, ["config", "reset", "--yes"])
    assert result.exit_code == 0
    text = user_policy.read_text()
    assert 'compat_tool = "Proton-9.0"' not in text   # overwritten
    assert "# [games]" in text                         # seeded with template


def test_config_reset_aborts_without_confirmation(user_policy):
    user_policy.write_text('[games]\ncompat_tool = "Proton-9.0"\n')
    # Respond "n" to the typer.confirm prompt.
    result = runner.invoke(cli.app, ["config", "reset"], input="n\n")
    assert result.exit_code != 0
    # File must be untouched.
    assert 'compat_tool = "Proton-9.0"' in user_policy.read_text()


def test_config_ignore_writes_override(user_policy):
    result = runner.invoke(cli.app, ["config", "ignore", "1495710"])
    assert result.exit_code == 0
    text = user_policy.read_text()
    assert "[overrides.1495710]" in text
    assert "ignore = true" in text


def test_config_ignore_rejects_non_numeric_appid(user_policy):
    result = runner.invoke(cli.app, ["config", "ignore", "not-a-number"])
    assert result.exit_code == 3


def test_initial_template_is_commented_factory():
    # Unit test on the seeding helper. Asserts the file content used to
    # initialise an absent user file: bundled factory, every active line
    # pre-commented, header explaining the override pattern.
    from steam_manager.io.policies_toml import render_initial_template as _render_initial_template
    text = _render_initial_template()
    assert "# [games]" in text
    assert '# compat_tool    = "Proton-CachyOS Latest"' in text
    assert "Deep-merged on top of the factory" in text
    # The seeded TOML must be valid (empty document — everything commented).
    import tomllib
    assert tomllib.loads(text) == {}


def test_config_edit_loops_on_invalid_then_valid_toml(user_policy, tmp_path, monkeypatch):
    # Pre-populate with an empty valid file so the editor is invoked.
    user_policy.write_text("")

    # Fake editor: writes invalid TOML on first call, then valid TOML on second.
    state = tmp_path / "state"
    state.write_text("0")
    editor = tmp_path / "fake_editor.sh"
    editor.write_text(
        "#!/usr/bin/env bash\n"
        "n=$(cat \"" + str(state) + "\")\n"
        "if [ \"$n\" = \"0\" ]; then\n"
        "  echo 'broken =' > \"$1\"\n"
        "  echo 1 > \"" + str(state) + "\"\n"
        "else\n"
        "  echo '[games]' > \"$1\"\n"
        "  echo 'compat_tool = \"Proton\"' >> \"$1\"\n"
        "fi\n"
    )
    editor.chmod(editor.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("EDITOR", str(editor))

    result = runner.invoke(cli.app, ["config", "edit"])
    assert result.exit_code == 0
    # State counter advanced from 0 to 1 (editor called once with broken,
    # once with valid input).
    assert state.read_text().strip() == "1"
    text = user_policy.read_text()
    assert "[games]" in text
    # The "# ERROR:" header injected during the loop must be cleaned up.
    assert "# ERROR:" not in text


