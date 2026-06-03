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


def _fake_multiselect(value):
    """Fake `render.multiselect`: returns the given selection (or `render.BACK`)."""
    return lambda *a, **kw: value


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


# ----- _merge_pending (pure) ------------------------------------------------


def test_merge_pending_last_edit_of_key_wins():
    pending = [_wizard.Change("games.compat_tool", None, "a")]
    out = _wizard._merge_pending(
        pending, [_wizard.Change("games.compat_tool", None, "b")])
    assert len(out) == 1
    assert out[0].new == "b"


def test_merge_pending_revert_to_disk_drops_entry():
    # Re-picking the on-disk value (a no-op) cancels the queued edit.
    pending = [_wizard.Change("games.compat_tool", "disk", "x")]
    out = _wizard._merge_pending(
        pending, [_wizard.Change("games.compat_tool", "disk", "disk")])
    assert out == []


def test_merge_pending_appends_distinct_keys():
    pending = [_wizard.Change("a.b", None, "1")]
    out = _wizard._merge_pending(pending, [_wizard.Change("c.d", None, "2")])
    assert {c.key for c in out} == {"a.b", "c.d"}


# ----- _pick_area (menu building) -------------------------------------------


def test_pick_area_shows_apply_discard_when_pending(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        render, "menu",
        lambda prompt, choices, **kw: captured.update(choices=choices))
    _wizard._pick_area(3)
    tuples = [c for c in captured["choices"] if isinstance(c, tuple)]
    values = [v for _, v in tuples]
    assert "apply" in values and "discard" in values
    assert any("(3)" in label for label, _ in tuples)


def test_pick_area_hides_apply_discard_when_empty(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        render, "menu",
        lambda prompt, choices, **kw: captured.update(choices=choices))
    _wizard._pick_area(0)
    values = [v for c in captured["choices"] if isinstance(c, tuple) for _, v in [c]]
    assert "apply" not in values and "discard" not in values


def test_pick_area_passes_default_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        render, "menu",
        lambda prompt, choices, **kw: captured.update(default=kw.get("default")))
    _wizard._pick_area(0, default="max-backups")
    assert captured["default"] == "max-backups"


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
    monkeypatch.setattr(render, "menu",
                        _Picker("proton_experimental"))
    changes = _wizard._flow_compat_games(ctx)
    assert len(changes) == 1
    assert changes[0].key == "games.compat_tool"
    assert changes[0].new == "proton_experimental"


def test_flow_compat_games_none_unsets(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    user_policy.write_text('[games]\ncompat_tool = "old"\n')
    monkeypatch.setattr(render, "menu", _Picker("__none__"))
    changes = _wizard._flow_compat_games(ctx)
    assert changes[0].new is _wizard._UNSET


def test_flow_compat_games_skip_returns_empty(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    monkeypatch.setattr(render, "menu", _Picker(render.BACK))
    assert _wizard._flow_compat_games(ctx) == []


def test_flow_compat_games_no_tools_returns_empty(user_policy, ctx, monkeypatch):
    """No appmanifest / no compatibilitytools.d → no picker, no changes."""
    monkeypatch.setattr(render, "menu",
                        lambda *a, **kw: pytest.fail("picker should not be invoked"))
    assert _wizard._flow_compat_games(ctx) == []


# ----- _flow_compat_single (game picker + tool picker) ---------------------


def test_flow_compat_single_creates_override(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    monkeypatch.setattr(render, "menu", _Picker(
        "111",                  # game picker
        "proton_experimental",  # tool picker
    ))
    changes = _wizard._flow_compat_single(ctx)
    assert changes[0].key == "overrides.111.compat_tool"


def test_flow_compat_single_cancel_at_game_picker(user_policy, ctx, monkeypatch, fake_steam):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    monkeypatch.setattr(render, "menu", _Picker(render.BACK))
    assert _wizard._flow_compat_single(ctx) == []


# ----- _flow_launch_games / single -----------------------------------------


def test_flow_launch_games_template(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "menu",
                        _Picker("scopebuddy -- %command%"))
    changes = _wizard._flow_launch_games(ctx)
    assert changes[0].key == "games.launch_options"
    assert changes[0].new == "scopebuddy -- %command%"


def test_flow_launch_games_custom(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "menu", _Picker("__custom__"))
    monkeypatch.setattr(render, "prompt_text", lambda *a, **kw: "WINEDEBUG=-all %command%")
    changes = _wizard._flow_launch_games(ctx)
    assert changes[0].new == "WINEDEBUG=-all %command%"


def test_flow_launch_games_none_clears(user_policy, ctx, monkeypatch):
    user_policy.write_text('[games]\nlaunch_options = "old"\n')
    monkeypatch.setattr(render, "menu", _Picker("__none__"))
    changes = _wizard._flow_launch_games(ctx)
    assert changes[0].new is _wizard._UNSET


def test_flow_launch_single_creates_override(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "menu", _Picker(
        "111",                          # game picker
        "scopebuddy -- %command%",      # template picker
    ))
    changes = _wizard._flow_launch_single(ctx)
    assert changes[0].key == "overrides.111.launch_options"


# ----- _flow_target_users (atomic) -----------------------------------------


def _no_multiselect(monkeypatch):
    """Install a multiselect that fails the test if reached.

    The sentinel modes (`active`/`*`) must NOT open the account picker.
    """
    def _boom(*a, **kw):
        raise AssertionError("multiselect should not be called for sentinel modes")
    monkeypatch.setattr(render, "multiselect", _boom)


def test_flow_target_users_specific_writes_list(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "menu", lambda *a, **kw: "specific")
    monkeypatch.setattr(render, "multiselect", _fake_multiselect(["testuser"]))
    changes = _wizard._flow_target_users(ctx)
    assert changes[0].key == "general.target_users"
    assert list(changes[0].new) == ["testuser"]


def test_flow_target_users_all_mode_writes_star(user_policy, ctx, monkeypatch):
    """Selecting the 'all local accounts' mode writes ['*'] without a picker."""
    monkeypatch.setattr(render, "menu", lambda *a, **kw: "*")
    _no_multiselect(monkeypatch)
    changes = _wizard._flow_target_users(ctx)
    assert list(changes[0].new) == ["*"]


def test_flow_target_users_active_mode_writes_active(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "menu", lambda *a, **kw: "active")
    _no_multiselect(monkeypatch)
    changes = _wizard._flow_target_users(ctx)
    assert list(changes[0].new) == ["active"]


def test_flow_target_users_cancel_at_mode(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "menu", lambda *a, **kw: render.BACK)
    _no_multiselect(monkeypatch)
    assert _wizard._flow_target_users(ctx) == []


def test_flow_target_users_default_mode_matches_current_sentinel(user_policy, ctx, monkeypatch):
    """The mode picker pre-positions on the mode the current value uses."""
    user_policy.write_text('[general]\ntarget_users = ["*"]\n')
    captured = {}
    monkeypatch.setattr(render, "menu",
                        lambda *a, **kw: captured.setdefault("default", kw.get("default")))
    _no_multiselect(monkeypatch)
    _wizard._flow_target_users(ctx)
    assert captured["default"] == "*"


def test_flow_target_users_specific_preselects_current(user_policy, ctx, monkeypatch):
    user_policy.write_text('[general]\ntarget_users = ["secondary"]\n')
    captured = {}

    def _capture(title, options, **kw):
        captured["choices"] = options
        return ["secondary"]

    # Current is an explicit name → mode defaults to 'specific'.
    monkeypatch.setattr(render, "menu",
                        lambda *a, **kw: kw.get("default"))
    monkeypatch.setattr(render, "multiselect", _capture)
    _wizard._flow_target_users(ctx)
    checked = {c.value: c.checked for c in captured["choices"] if isinstance(c, questionary.Choice)}
    assert checked["secondary"] is True
    assert checked["testuser"] is False


def test_flow_target_users_empty_selection(user_policy, ctx, monkeypatch):
    monkeypatch.setattr(render, "menu", lambda *a, **kw: "specific")
    monkeypatch.setattr(render, "multiselect", _fake_multiselect([]))
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
    monkeypatch.setattr(render, "multiselect", _fake_multiselect(["111", "222"]))
    changes = _wizard._flow_ignore_list(ctx)
    assert {c.key for c in changes} == {"overrides.111.ignore", "overrides.222.ignore"}
    assert all(c.new is True for c in changes)


def test_flow_ignore_list_toggle_removes(user_policy, ctx, monkeypatch):
    user_policy.write_text(
        '[overrides.111]\nignore = true\n\n'
        '[overrides.222]\nignore = true\n'
    )
    monkeypatch.setattr(render, "multiselect", _fake_multiselect(["111"]))
    changes = _wizard._flow_ignore_list(ctx)
    assert len(changes) == 1
    assert changes[0].key == "overrides.222.ignore"
    assert changes[0].new is _wizard._UNSET


def test_flow_ignore_list_no_change(user_policy, ctx, monkeypatch):
    user_policy.write_text('[overrides.111]\nignore = true\n')
    monkeypatch.setattr(render, "multiselect", _fake_multiselect(["111"]))
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
    monkeypatch.setattr(render, "menu", _Picker(render.BACK))
    _wizard.run()


def test_run_applies_pending_then_exits(user_policy, ctx, monkeypatch):
    # Queue an edit, Apply it, then exit. Edits are batched: the write only
    # happens on Apply, not per-edit.
    monkeypatch.setattr(render, "menu", _Picker(
        "max-backups",   # queue an edit
        "apply",         # commit pending
        render.BACK,          # pending now empty → exits without prompting
    ))
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: 7)
    _wizard.run()
    doc = tomlkit.parse(user_policy.read_text())
    assert doc["general"]["max_backups"] == 7


def test_run_batches_then_applies_target_users(user_policy, ctx, monkeypatch):
    # An edit reaches disk only after Apply, exercising the pending batch.
    monkeypatch.setattr(render, "menu", _Picker(
        "target-users",  # menu
        "*",             # mode picker → all local accounts
        "apply",         # menu: commit
        render.BACK,          # menu
    ))
    _wizard.run()
    doc = tomlkit.parse(user_policy.read_text())
    assert list(doc["general"]["target_users"]) == ["*"]


def test_run_show_does_not_write(user_policy, ctx, monkeypatch, capsys):
    monkeypatch.setattr(render, "menu", _Picker("show", render.BACK))
    _wizard.run()
    assert not user_policy.exists()
    out = capsys.readouterr().out
    assert "Current configuration" in out


def test_run_exit_discards_pending_when_confirmed(user_policy, ctx, monkeypatch):
    # Exiting with queued edits prompts; confirming discards them (no write).
    monkeypatch.setattr(render, "menu",
                        _Picker("max-backups", render.BACK))
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: 99)
    monkeypatch.setattr(render, "confirm", lambda *a, **kw: True)
    _wizard.run()
    assert not user_policy.exists()


def test_run_discard_entry_drops_pending(user_policy, ctx, monkeypatch):
    # The Discard menu entry clears queued edits without writing.
    monkeypatch.setattr(render, "menu",
                        _Picker("max-backups", "discard", render.BACK))
    monkeypatch.setattr(render, "prompt_int", lambda *a, **kw: 99)
    _wizard.run()
    assert not user_policy.exists()


def test_run_filters_noop_changes(user_policy, ctx, monkeypatch):
    user_policy.write_text('[general]\nmax_backups = 10\n')
    monkeypatch.setattr(render, "menu",
                        _Picker("max-backups", render.BACK))
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
    # user_policy fixture set the path; we don't write the file. The factory's
    # games.launch_options is "scopebuddy -- %command%".
    assert _wizard._effective("games.launch_options") == "scopebuddy -- %command%"


def test_effective_compat_tool_unset_in_factory(user_policy):
    """The factory ships no games.compat_tool — users pick one explicitly, so
    a fresh install never writes a bogus tech_name to Steam."""
    assert _wizard._effective("games.compat_tool") is None


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
