"""Tests for `cli/_wizard.py` — the granular `config wizard` flow.

The wizard's design separates decision (what changes to propose) from
side-effect (write the file). Each test exercises one sub-flow by
monkey-patching the picker functions and asserts on the returned
`Change` list, then `_apply_changes` is tested separately as a pure
function over a Change list.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import questionary
import tomlkit

from steam_manager import render
from steam_manager.io import discovery
from steam_manager.cli import _wizard
from steam_manager.io import policies_toml


# ----- helpers --------------------------------------------------------------


class _Picker:
    """Queue of responses for a picker function. Raises if exhausted."""

    def __init__(self, *responses):
        self._iter = iter(responses)

    def __call__(self, *args, **kwargs):
        try:
            return next(self._iter)
        except StopIteration:
            raise AssertionError(f"picker called more times than expected; args={args}")


class _FakeCheckbox:
    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


def _fake_checkbox(value):
    return lambda *a, **kw: _FakeCheckbox(value)


@pytest.fixture
def user_policy(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "user.toml"
    monkeypatch.setenv("STEAM_MANAGER_USER_POLICY", str(p))
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    return p


@pytest.fixture
def ctx(fake_steam: Path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    return discovery.discover(steam_root=fake_steam)


def _write_proton_appmanifest(steam_root: Path, appid: str, name: str, installdir: str) -> None:
    (steam_root / "steamapps" / f"appmanifest_{appid}.acf").write_text(
        '"AppState"\n{\n'
        f'    "appid"      "{appid}"\n'
        f'    "name"       "{name}"\n'
        '    "StateFlags" "4"\n'
        f'    "installdir" "{installdir}"\n'
        '}\n'
    )


# ----- _is_noop (pure unit) -------------------------------------------------


def test_is_noop_unset_when_already_none():
    assert _wizard._is_noop(_wizard.Change("k", None, _wizard._UNSET)) is True


def test_is_noop_unset_when_value_existed():
    assert _wizard._is_noop(_wizard.Change("k", "x", _wizard._UNSET)) is False


def test_is_noop_same_value():
    assert _wizard._is_noop(_wizard.Change("k", "x", "x")) is True


def test_is_noop_different_value():
    assert _wizard._is_noop(_wizard.Change("k", "x", "y")) is False


def test_is_noop_same_list():
    assert _wizard._is_noop(_wizard.Change("k", ["a", "b"], ["a", "b"])) is True


# ----- _apply_changes -------------------------------------------------------


def test_apply_changes_set_creates_section(user_policy: Path):
    _wizard._apply_changes([_wizard.Change("games.compat_tool", None, "proton_9")])
    doc = tomlkit.parse(user_policy.read_text())
    assert doc["games"]["compat_tool"] == "proton_9"


def test_apply_changes_unset_drops_empty_table(user_policy: Path):
    user_policy.write_text('[games]\ncompat_tool = "old"\n')
    _wizard._apply_changes([_wizard.Change("games.compat_tool", "old", _wizard._UNSET)])
    text = user_policy.read_text()
    assert "compat_tool" not in text
    assert "[games]" not in text


def test_apply_changes_multiple_atomic(user_policy: Path):
    _wizard._apply_changes([
        _wizard.Change("games.compat_tool", None, "proton_9"),
        _wizard.Change("general.max_backups", 10, 25),
    ])
    doc = tomlkit.parse(user_policy.read_text())
    assert doc["games"]["compat_tool"] == "proton_9"
    assert doc["general"]["max_backups"] == 25


# ----- _flow_compat_games (one prompt only) --------------------------------


def test_flow_compat_games_sets_value(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    monkeypatch.setattr(render, "select_one_interactive",
                        _Picker("proton_experimental"))
    changes = _wizard._flow_compat_games(ctx)
    assert len(changes) == 1
    assert changes[0].key == "games.compat_tool"
    assert changes[0].new == "proton_experimental"


def test_flow_compat_games_none_unsets(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    user_policy.write_text('[games]\ncompat_tool = "old"\n')
    monkeypatch.setattr(render, "select_one_interactive", _Picker("__none__"))
    changes = _wizard._flow_compat_games(ctx)
    assert changes[0].new is _wizard._UNSET


def test_flow_compat_games_skip_returns_empty(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    monkeypatch.setattr(render, "select_one_interactive", _Picker("__keep__"))
    assert _wizard._flow_compat_games(ctx) == []


def test_flow_compat_games_no_tools_returns_empty(user_policy, ctx, monkeypatch):
    """No appmanifest / no compatibilitytools.d → no picker, no changes."""
    monkeypatch.setattr(render, "select_one_interactive",
                        lambda *a, **kw: pytest.fail("picker should not be invoked"))
    assert _wizard._flow_compat_games(ctx) == []


# ----- _flow_compat_single (game picker + tool picker) ---------------------


def test_flow_compat_single_creates_override(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    monkeypatch.setattr(render, "select_one_interactive", _Picker(
        "111",                  # game picker
        "proton_experimental",  # tool picker
    ))
    changes = _wizard._flow_compat_single(ctx)
    assert changes[0].key == "overrides.111.compat_tool"


def test_flow_compat_single_cancel_at_game_picker(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    monkeypatch.setattr(render, "select_one_interactive", _Picker(None))
    assert _wizard._flow_compat_single(ctx) == []


# ----- _flow_launch_games / single -----------------------------------------


def test_flow_launch_games_template(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "select_one_interactive",
                        _Picker("scopebuddy -- %command%"))
    changes = _wizard._flow_launch_games(ctx)
    assert changes[0].key == "games.launch_options"
    assert changes[0].new == "scopebuddy -- %command%"


def test_flow_launch_games_custom(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "select_one_interactive", _Picker("__custom__"))
    monkeypatch.setattr(render, "prompt_text", lambda *a, **kw: "WINEDEBUG=-all %command%")
    changes = _wizard._flow_launch_games(ctx)
    assert changes[0].new == "WINEDEBUG=-all %command%"


def test_flow_launch_games_none_clears(user_policy, ctx, monkeypatch):
    user_policy.write_text('[games]\nlaunch_options = "old"\n')
    monkeypatch.setattr(render, "select_one_interactive", _Picker("__none__"))
    changes = _wizard._flow_launch_games(ctx)
    assert changes[0].new is _wizard._UNSET


def test_flow_launch_single_creates_override(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "select_one_interactive", _Picker(
        "111",                          # game picker
        "scopebuddy -- %command%",      # template picker
    ))
    changes = _wizard._flow_launch_single(ctx)
    assert changes[0].key == "overrides.111.launch_options"


# ----- _flow_target_users (atomic) -----------------------------------------


def test_flow_target_users_writes_list(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(questionary, "checkbox", _fake_checkbox(["testuser"]))
    changes = _wizard._flow_target_users(ctx)
    assert changes[0].key == "general.target_users"
    assert list(changes[0].new) == ["testuser"]


def test_flow_target_users_star_dominates(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(questionary, "checkbox", _fake_checkbox(["*", "testuser"]))
    changes = _wizard._flow_target_users(ctx)
    assert list(changes[0].new) == ["*"]


def test_flow_target_users_preselects_current(user_policy, ctx, monkeypatch):
    user_policy.write_text('[general]\ntarget_users = ["secondary"]\n')
    captured = {}

    def _capture(prompt, choices, **kw):
        captured["choices"] = choices
        return _FakeCheckbox(["secondary"])

    monkeypatch.setattr(questionary, "checkbox", _capture)
    _wizard._flow_target_users(ctx)
    # Filter to actual Choice objects (skip the Separator).
    checked = {c.value: c.checked for c in captured["choices"] if isinstance(c, questionary.Choice)}
    assert checked["secondary"] is True
    assert checked["testuser"] is False


def test_flow_target_users_empty_selection(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(questionary, "checkbox", _fake_checkbox([]))
    assert _wizard._flow_target_users(ctx) == []


# ----- _flow_max_backups (atomic) ------------------------------------------


def test_flow_max_backups_writes_int(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: 25)
    changes = _wizard._flow_max_backups(ctx)
    assert changes[0].key == "general.max_backups"
    assert changes[0].new == 25


def test_flow_max_backups_cancel(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: None)
    assert _wizard._flow_max_backups(ctx) == []


# ----- _flow_ignore_list (toggle) ------------------------------------------


def test_flow_ignore_list_adds_games(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(questionary, "checkbox", _fake_checkbox(["111", "222"]))
    changes = _wizard._flow_ignore_list(ctx)
    assert {c.key for c in changes} == {"overrides.111.ignore", "overrides.222.ignore"}
    assert all(c.new is True for c in changes)


def test_flow_ignore_list_toggle_removes(user_policy, ctx, monkeypatch):
    user_policy.write_text(
        '[overrides.111]\nignore = true\n\n'
        '[overrides.222]\nignore = true\n'
    )
    monkeypatch.setattr(questionary, "checkbox", _fake_checkbox(["111"]))
    changes = _wizard._flow_ignore_list(ctx)
    assert len(changes) == 1
    assert changes[0].key == "overrides.222.ignore"
    assert changes[0].new is _wizard._UNSET


def test_flow_ignore_list_no_change(user_policy, ctx, monkeypatch):
    user_policy.write_text('[overrides.111]\nignore = true\n')
    monkeypatch.setattr(questionary, "checkbox", _fake_checkbox(["111"]))
    assert _wizard._flow_ignore_list(ctx) == []


# ----- _flow_reset ---------------------------------------------------------


def test_flow_reset_unlinks_file(user_policy: Path, monkeypatch):
    user_policy.write_text('[games]\ncompat_tool = "x"\n')
    monkeypatch.setattr(render, "confirm", lambda *a, **kw: True)
    _wizard._flow_reset()
    assert not user_policy.exists()


def test_flow_reset_cancel_leaves_file(user_policy: Path, monkeypatch):
    user_policy.write_text('[games]\ncompat_tool = "x"\n')
    monkeypatch.setattr(render, "confirm", lambda *a, **kw: False)
    _wizard._flow_reset()
    assert user_policy.exists()


def test_flow_reset_no_op_if_missing(user_policy: Path, monkeypatch):
    monkeypatch.setattr(render, "confirm",
                        lambda *a, **kw: pytest.fail("should not prompt"))
    _wizard._flow_reset()
    assert not user_policy.exists()


# ----- main loop -----------------------------------------------------------


def test_run_exits_immediately(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "select_one_interactive", _Picker("exit"))
    _wizard.run()


def test_run_dispatches_max_backups_then_exits(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "select_one_interactive", _Picker(
        "max-backups",   # main menu first
        "exit",          # main menu, second iteration
    ))
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: 7)
    monkeypatch.setattr(render, "confirm", lambda *a, **kw: True)
    _wizard.run()
    doc = tomlkit.parse(user_policy.read_text())
    assert doc["general"]["max_backups"] == 7


def test_run_show_does_not_write(user_policy, ctx, monkeypatch, capsys):
    monkeypatch.setattr(render, "select_one_interactive", _Picker("show", "exit"))
    _wizard.run()
    assert not user_policy.exists()
    out = capsys.readouterr().out
    assert "Current configuration" in out


def test_run_discards_on_no_confirm(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "select_one_interactive",
                        _Picker("max-backups", "exit"))
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: 99)
    monkeypatch.setattr(render, "confirm", lambda *a, **kw: False)
    _wizard.run()
    assert not user_policy.exists()


def test_run_filters_noop_changes(user_policy, ctx, monkeypatch):
    user_policy.write_text('[general]\nmax_backups = 10\n')
    monkeypatch.setattr(render, "select_one_interactive",
                        _Picker("max-backups", "exit"))
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: 10)
    monkeypatch.setattr(render, "confirm",
                        lambda *a, **kw: pytest.fail("no-op should skip confirm"))
    _wizard.run()
    assert user_policy.read_text() == '[general]\nmax_backups = 10\n'


# ----- print helpers (smoke) -----------------------------------------------


def test_print_current_config_does_not_crash(user_policy, ctx, capsys):
    user_policy.write_text(
        '[games]\ncompat_tool = "proton_9"\n\n'
        '[overrides.111]\nignore = true\n'
    )
    _wizard._print_current_config()
    out = capsys.readouterr().out
    assert "Current configuration" in out
    assert "proton_9" in out


def test_effective_returns_user_override_over_factory(user_policy):
    """`_effective` is the merged-read used to pre-populate every picker.
    If a user override shadows the factory, that's the value the wizard
    must display — getting this wrong would mean pickers default to the
    factory value even after the user has set their own."""
    user_policy.write_text('[games]\ncompat_tool = "MyCustomProton"\n')
    assert _wizard._effective("games.compat_tool") == "MyCustomProton"


def test_effective_returns_factory_when_user_missing(user_policy):
    """No user override → fall back to bundled factory value."""
    # user_policy fixture set the path; we don't write the file. The
    # factory's `games.compat_tool` is "Proton-CachyOS Latest".
    assert _wizard._effective("games.compat_tool") == "Proton-CachyOS Latest"


def test_effective_returns_none_for_missing_key(user_policy):
    assert _wizard._effective("nonexistent.key") is None


def test_print_pending_changes_does_not_crash(capsys):
    changes = [
        _wizard.Change("games.compat_tool", None, "proton_9"),
        _wizard.Change("general.max_backups", 10, _wizard._UNSET),
    ]
    _wizard._print_pending_changes(changes)
    out = capsys.readouterr().out
    assert "Pending changes" in out
    assert "(unset)" in out
