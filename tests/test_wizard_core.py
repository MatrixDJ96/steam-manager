"""Tests for `cli/_wizard_core.py` — the pure, front-end-agnostic config core.

These drive `load_state` + every reducer directly on the `fake_steam` tree and
assert on the returned `Change` objects / `WizardState`. No questionary, no
Textual, no filesystem mocking beyond the real user-policy path — the same
fast lane the classic flow's Change tests live in.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from steam_manager.cli import _wizard_core as core
from steam_manager.cli._common import steam_root
from steam_manager.cli._wizard_core import _UNSET, Change
from steam_manager.io import discovery, policies_toml


@pytest.fixture
def env(fake_steam: Path, tmp_path: Path, monkeypatch) -> Path:
    """Point steam_root at fake_steam and the user policy at a tmp file
    (factory still merged underneath). Returns the user-policy path."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    user = tmp_path / "user.toml"
    monkeypatch.setenv("STEAM_MANAGER_USER_POLICY", str(user))
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    return user


@pytest.fixture
def state(env) -> core.WizardState:
    return core.load_state()


# ----- load_state -----------------------------------------------------------


def test_load_state_matches_installed_games(state, env):
    ctx = discovery.discover(steam_root=steam_root())
    expected = {a.appid for a in core._installed_games(ctx)}
    assert expected, "fake_steam should expose at least one installed game"
    assert {g.appid for g in state.data.games} == expected


def test_load_state_sorted_by_name(state):
    names = [g.name.lower() for g in state.data.games]
    assert names == sorted(names)


def test_load_state_degrades_without_steam(tmp_path, monkeypatch):
    user = tmp_path / "user.toml"
    monkeypatch.setenv("STEAM_MANAGER_USER_POLICY", str(user))
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    monkeypatch.delenv("STEAM_MANAGER_STEAM_ROOT", raising=False)

    def _no_steam(**_kw):
        raise FileNotFoundError("no steam")

    monkeypatch.setattr("steam_manager.io.discovery.discover", _no_steam)
    s = core.load_state()
    assert s.data.steam_found is False
    assert s.data.games == () and s.data.users == () and s.data.tools == ()
    # the policy document still loads, so global defaults stay editable
    assert s.loaded("general.max_backups") == 10
    assert core.set_max_backups(s, "5").pending == (Change("general.max_backups", 10, 5),)


def test_load_state_baseline_values(state):
    assert state.loaded("general.max_backups") == 10
    assert list(state.loaded("general.target_users")) == ["active"]
    assert state.loaded("games.compat_tool") is None
    assert state.loaded("games.launch_options") == "scopebuddy -- %command%"
    assert state.pending == ()


def test_load_state_gamerow_resolves_section_policy(state):
    # No per-AppID overrides in factory -> every game resolves the games
    # section's launch_options and an unset compat_tool.
    for g in state.data.games:
        assert g.policy_compat is None
        assert g.policy_launch == "scopebuddy -- %command%"
        assert g.ignored is False


# ----- compat tool ----------------------------------------------------------


def test_set_compat_tool_queues_change(state):
    s = core.set_compat_tool(state, "games", "proton_experimental")
    assert s.pending == (Change("games.compat_tool", None, "proton_experimental"),)


def test_set_compat_tool_none_is_noop_when_unset(state):
    assert state.loaded("games.compat_tool") is None
    assert core.set_compat_tool(state, "games", None).pending == ()


def test_set_compat_tool_per_game_scope(state):
    appid = state.data.games[0].appid
    s = core.set_compat_tool(state, f"overrides.{appid}", "proton_9")
    assert s.pending == (Change(f"overrides.{appid}.compat_tool", None, "proton_9"),)


def test_revert_to_loaded_drops_pending(state):
    base = state.loaded("games.compat_tool")
    s1 = core.set_compat_tool(state, "games", "proton_experimental")
    assert len(s1.pending) == 1
    s2 = core.set_compat_tool(s1, "games", base)  # re-pick the on-disk value
    assert s2.pending == ()


# ----- launch options -------------------------------------------------------


def test_set_launch_options_value_queues_change(state):
    s = core.set_launch_options(state, "overrides.222", "mangohud %command%")
    assert s.pending == (
        Change("overrides.222.launch_options", None, "mangohud %command%"),
    )


def test_set_launch_options_blank_on_unset_is_noop(state):
    assert state.loaded("overrides.222.launch_options") is None
    assert core.set_launch_options(state, "overrides.222", "   ").pending == ()


def test_set_launch_options_blank_clears_existing(state):
    # games.launch_options is set in factory -> clearing it queues an unset.
    s = core.set_launch_options(state, "games", "")
    assert s.pending == (
        Change("games.launch_options", "scopebuddy -- %command%", _UNSET),
    )


# ----- max backups (validation in the pure core) ----------------------------


def test_set_max_backups_valid(state):
    assert core.set_max_backups(state, "5").pending == (
        Change("general.max_backups", 10, 5),
    )


def test_set_max_backups_leading_zero(state):
    assert core.set_max_backups(state, "08").pending == (
        Change("general.max_backups", 10, 8),
    )


@pytest.mark.parametrize("bad", ["", "abc", "0", "-3", "  "])
def test_set_max_backups_invalid_rejected(state, bad):
    assert core.set_max_backups(state, bad).pending == ()


# ----- target users ---------------------------------------------------------


def test_set_target_users_all(state):
    s = core.set_target_users(state, ["*"])
    assert len(s.pending) == 1
    c = s.pending[0]
    assert c.key == "general.target_users"
    assert list(c.old) == ["active"]
    assert list(c.new) == ["*"]


def test_set_target_users_back_to_active_is_noop(state):
    assert core.set_target_users(state, ["active"]).pending == ()


# ----- ignore ---------------------------------------------------------------


def test_toggle_ignore_queues_then_reverts(state):
    appid = state.data.games[0].appid
    s1 = core.toggle_ignore(state, appid)
    assert s1.pending == (Change(f"overrides.{appid}.ignore", None, True),)
    assert core.toggle_ignore(s1, appid).pending == ()


def test_set_ignored_batch(state):
    appids = [g.appid for g in state.data.games]
    s = core.set_ignored(state, set(appids))
    assert sorted(c.key for c in s.pending) == sorted(
        f"overrides.{a}.ignore" for a in appids
    )
    assert all(c.new is True for c in s.pending)


# ----- effective vs loaded overlay ------------------------------------------


def test_effective_overlays_pending_loaded_does_not(state):
    s = core.set_compat_tool(state, "games", "proton_experimental")
    assert s.effective("games.compat_tool") == "proton_experimental"
    assert s.loaded("games.compat_tool") is None


# ----- apply / discard / reset ----------------------------------------------


def test_apply_writes_user_policy_once_and_counts(state, env):
    s = core.set_compat_tool(state, "games", "proton_experimental")
    s = core.set_max_backups(s, "7")
    assert core.apply(s) == 2
    assert env.exists()
    doc = policies_toml.load_doc()
    assert policies_toml.get_dotted(doc, "games.compat_tool") == "proton_experimental"
    assert policies_toml.get_dotted(doc, "general.max_backups") == 7


def test_discard_clears_pending(state):
    s = core.set_compat_tool(state, "games", "proton_experimental")
    assert s.pending
    assert core.discard(s).pending == ()


def test_can_reset_and_reset(state, env):
    assert core.can_reset() is False
    core.apply(core.set_max_backups(state, "9"))
    assert core.can_reset() is True
    core.reset()
    assert core.can_reset() is False
    assert not env.exists()
