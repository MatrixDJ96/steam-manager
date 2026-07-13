"""Textual Pilot tests for the scopebuddy dashboard (marked `tui`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from steam_manager.io import discovery
from tests.tui_helpers import wait_for_screen

pytestmark = pytest.mark.tui


@pytest.fixture
def scb_env(fake_steam: Path, tmp_path: Path, monkeypatch) -> Path:
    """fake_steam + an isolated ScopeBuddy dir. Game 111 gets scopebuddy launch
    options via the primary user's localconfig; an orphan conf sits beside it.
    Returns the scb dir."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    scb = tmp_path / "scb"
    scb.mkdir()
    monkeypatch.setenv("STEAM_MANAGER_SCB_DIR", str(scb))
    (scb / "424242.conf").write_text("# orphan\n")
    ctx = discovery.discover(steam_root=fake_steam)
    user = discovery.list_users(ctx)[0]
    game = discovery.list_apps(ctx)[0]
    from steam_manager.io import localconfig_vdf
    localconfig_vdf.set_launch_options(user, game.appid, "scopebuddy -- %command%")
    return scb


def _scb_app(scb: Path):
    from steam_manager.cli.tui.scb_app import ScbApp
    from steam_manager.cli._common import steam_root
    ctx = discovery.discover(steam_root=steam_root())
    apps = [a for a in discovery.list_apps(ctx) if a.installed]
    user = discovery.list_users(ctx)[0]
    from steam_manager.io import localconfig_vdf
    launch = {a.appid: localconfig_vdf.get_launch_options(user, a.appid) for a in apps}
    return ScbApp(scb, apps, launch)


async def test_dashboard_lists_status_and_orphans(scb_env):
    from textual.widgets import DataTable, Static
    app = _scb_app(scb_env)
    async with app.run_test() as pilot:
        await pilot.pause()
        games = app.query_one("#games", DataTable)
        assert games.row_count >= 2
        summary = str(app.query_one("#summary", Static).render())
        assert "1 missing" in summary and "1 orphan" in summary
        orphans = app.query_one("#orphans", DataTable)
        assert orphans.row_count == 1


async def test_row_modal_inits_stub(scb_env):
    from steam_manager.cli.tui.widgets import ScbRowScreen
    app = _scb_app(scb_env)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")               # first row (name-sorted)
        await wait_for_screen(pilot, app, ScbRowScreen)
        await pilot.press("enter")               # highlighted entry = init when missing
        await pilot.pause()
    # exactly the missing game's stub was created
    created = [p.name for p in scb_env.glob("*.conf")]
    assert len(created) == 2 and "424242.conf" in created


async def test_bulk_init_creates_all_missing(scb_env):
    from steam_manager.cli.tui.widgets import ConfirmScreen
    app = _scb_app(scb_env)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await wait_for_screen(pilot, app, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
    assert len(list(scb_env.glob("*.conf"))) == 2


async def test_delete_orphan_checkpoints_then_removes(scb_env, tmp_path, monkeypatch):
    from steam_manager.cli.tui.widgets import ConfirmScreen, ScbRowScreen
    from steam_manager.io import backups
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "bk"))
    app = _scb_app(scb_env)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#orphans").focus()
        await pilot.pause()
        await pilot.press("enter")
        await wait_for_screen(pilot, app, ScbRowScreen)
        # an orphan enables both editor and delete; editor is the highlighted
        # first-enabled entry, so step down once to reach delete.
        await pilot.press("down", "enter")
        await wait_for_screen(pilot, app, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
    assert not (scb_env / "424242.conf").exists()
    cps = backups.list_checkpoints(tmp_path / "bk")
    assert len(cps) == 1 and cps[0]["manifest"]["trigger"] == "scb-delete"


async def test_editor_action_invokes_chosen_editor(scb_env, monkeypatch):
    from steam_manager.cli.tui.widgets import ScbRowScreen
    import steam_manager.cli.tui.scb_app as scb_app_mod
    calls: list[list[str]] = []
    monkeypatch.setattr(scb_app_mod, "choose_editor", lambda: ["true"])
    monkeypatch.setattr(scb_app_mod.subprocess, "call",
                        lambda argv: calls.append(argv) or 0)
    app = _scb_app(scb_env)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#orphans").focus()
        await pilot.pause()
        await pilot.press("enter")
        await wait_for_screen(pilot, app, ScbRowScreen)
        # editor is the highlighted first-enabled entry for an orphan (init is
        # disabled, the .conf exists), so a single Enter selects it.
        await pilot.press("enter")
        await pilot.pause()
    assert calls and calls[0][-1].endswith("424242.conf")
