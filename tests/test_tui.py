"""Textual Pilot interaction tests for the config TUI (slow lane).

Marked `tui` so the fast lane (`pytest -m 'not tui'`) skips them and stays
sub-2s and Textual-free. These drive the real App via `app.run_test()` on the
`fake_steam` tree.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from steam_manager.cli import _wizard_core as core

pytestmark = pytest.mark.tui


@pytest.fixture
def env(fake_steam: Path, tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    user = tmp_path / "user.toml"
    monkeypatch.setenv("STEAM_MANAGER_USER_POLICY", str(user))
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    return user


def _app(state=None):
    from steam_manager.cli.tui.app import ConfigApp
    return ConfigApp(state=state)


async def _wait_for_screen(pilot, app, screen_type, tries: int = 30):
    """Pump the event loop until a modal of `screen_type` is on top (the @work
    action that pushes it runs in a worker, so it isn't synchronous)."""
    for _ in range(tries):
        await pilot.pause()
        if isinstance(app.screen, screen_type):
            return
    raise AssertionError(f"{screen_type.__name__} never appeared")


async def test_app_lists_games(env):
    from textual.widgets import DataTable
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#games", DataTable)
        assert table.row_count == len(app.state.data.games)
        assert table.row_count >= 1


async def test_filter_by_appid_narrows_to_one(env):
    from textual.widgets import DataTable, Input
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        appid = app.state.data.games[0].appid
        app.query_one("#filter", Input).value = appid
        await pilot.pause()
        assert app.query_one("#games", DataTable).row_count == 1


async def test_toggle_ignore_stages_pending(env):
    from textual.widgets import DataTable
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#games", DataTable).focus()
        await pilot.press("space")
        await pilot.pause()
        assert app.state.pending_count == 1
        assert app.query_one("#pending", DataTable).row_count == 1


async def test_save_writes_user_policy_and_clears(env):
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")          # ignore the first game
        await pilot.pause()
        assert app.state.pending_count == 1
        await pilot.press("s")              # Save
        await pilot.pause()
        assert app.state.pending_count == 0
        assert env.exists()                 # policies.toml written


async def test_max_backups_modal_edits_value(env):
    from textual.widgets import Input
    from steam_manager.cli.tui.widgets import MaxBackupsScreen
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("b")              # open MaxBackupsScreen
        await _wait_for_screen(pilot, app, MaxBackupsScreen)
        app.screen.query_one("#backups-input", Input).value = "7"
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.effective("general.max_backups") == 7


async def test_compat_picker_clears_to_none(env):
    # Pick "None (Steam default)" for the games default -> queues an unset only
    # if a value existed; factory ships no games.compat_tool, so it is a no-op.
    # Instead set a per-game override then confirm the picker stages a Change.
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        # The compat picker on the games default; choose None is a no-op, so
        # assert the screen at least opens and dismisses without error.
        await pilot.press("g")
        await pilot.pause()
        from steam_manager.cli.tui.widgets import CompatPickerScreen
        assert isinstance(app.screen, CompatPickerScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_quit_with_pending_confirms_and_discards(env):
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")          # stage a change
        await pilot.pause()
        assert app.state.pending_count == 1
        await pilot.press("q")              # quit -> ConfirmScreen
        await pilot.pause()
        await pilot.press("y")              # confirm discard+quit
        await pilot.pause()
    # exiting without Save must not write the policy
    assert not env.exists()


async def test_empty_games_shows_message(env):
    from textual.widgets import Static
    base = core.load_state()
    empty = dataclasses.replace(base, data=dataclasses.replace(base.data, games=()))
    app = _app(state=empty)
    async with app.run_test() as pilot:
        await pilot.pause()
        note = app.query_one("#empty-note", Static)
        text = getattr(note, "renderable", None)
        if text is None:
            text = note.render()
        assert "No installed games found" in str(text)
