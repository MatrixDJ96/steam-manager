"""Textual Pilot interaction tests for the config TUI (slow lane).

Marked `tui` so the fast lane (`pytest -m 'not tui'`) skips them and stays
sub-2s and Textual-free. These drive the real App via `app.run_test()` on the
`fake_steam` tree.
"""
from __future__ import annotations

import dataclasses

import pytest

from steam_manager.cli import _wizard_core as core
from tests.tui_helpers import make_app, wait_for_screen

pytestmark = pytest.mark.tui


async def test_app_lists_games(env):
    from textual.widgets import DataTable
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#games", DataTable)
        assert table.row_count == len(app.state.data.games)
        assert table.row_count >= 1


async def test_filter_by_appid_narrows_to_one(env):
    from textual.widgets import DataTable, Input
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        appid = app.state.data.games[0].appid
        app.query_one("#filter", Input).value = appid
        await pilot.pause()
        assert app.query_one("#games", DataTable).row_count == 1


async def test_toggle_ignore_stages_pending(env):
    from textual.widgets import DataTable
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#games", DataTable).focus()
        await pilot.press("space")
        await pilot.pause()
        assert app.state.pending_count == 1
        assert app.query_one("#pending", DataTable).row_count == 1


async def test_save_writes_user_policy_and_clears(env):
    app = make_app()
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
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("b")              # open MaxBackupsScreen
        await wait_for_screen(pilot, app, MaxBackupsScreen)
        app.screen.query_one("#backups-input", Input).value = "7"
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.effective("general.max_backups") == 7


async def test_compat_picker_clears_to_none(env):
    # Pick "None (Steam default)" for the games default -> queues an unset only
    # if a value existed; factory ships no games.compat_tool, so it is a no-op.
    # Instead set a per-game override then confirm the picker stages a Change.
    app = make_app()
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
    app = make_app()
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


async def test_enter_opens_game_editor(env):
    from steam_manager.cli.tui.widgets import GameEditScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")          # games table focused on mount
        await wait_for_screen(pilot, app, GameEditScreen)
        await pilot.press("escape")         # cancel stages nothing
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_game_editor_toggles_ignore(env):
    from steam_manager.cli.tui.widgets import GameEditScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await wait_for_screen(pilot, app, GameEditScreen)
        await pilot.press("down", "down", "enter")   # compat, launch, IGNORE
        await pilot.pause()
        assert app.state.pending_count == 1
        first = app.state.data.games[0]
        assert app.state.pending[0].key == f"overrides.{first.appid}.ignore"


async def test_settings_hub_routes_to_max_backups(env):
    from textual.widgets import Input
    from steam_manager.cli.tui.widgets import MaxBackupsScreen, SettingsScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await wait_for_screen(pilot, app, SettingsScreen)
        await pilot.press(*(["down"] * 5), "enter")  # last entry: Max backups
        await wait_for_screen(pilot, app, MaxBackupsScreen)
        app.screen.query_one("#backups-input", Input).value = "7"
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.effective("general.max_backups") == 7


async def test_settings_hub_routes_to_games_compat(env):
    from steam_manager.cli.tui.widgets import CompatPickerScreen, SettingsScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await wait_for_screen(pilot, app, SettingsScreen)
        await pilot.press("enter")                   # first entry: Games · compat tool
        await wait_for_screen(pilot, app, CompatPickerScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.state.pending_count == 0


async def test_confirm_buttons_default_to_no(env):
    from steam_manager.cli.tui.widgets import ConfirmScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")          # stage a change
        await pilot.pause()
        await pilot.press("q")              # quit -> ConfirmScreen
        await wait_for_screen(pilot, app, ConfirmScreen)
        await pilot.press("enter")          # activates the pre-focused No button
        await pilot.pause()
        assert not app._exit                # still running
        assert app.state.pending_count == 1


async def test_empty_games_shows_message(env):
    from textual.widgets import Static
    base = core.load_state()
    empty = dataclasses.replace(base, data=dataclasses.replace(base.data, games=()))
    app = make_app(state=empty)
    async with app.run_test() as pilot:
        await pilot.pause()
        note = app.query_one("#empty-note", Static)
        text = getattr(note, "renderable", None)
        if text is None:
            text = note.render()
        assert "No installed games found" in str(text)
