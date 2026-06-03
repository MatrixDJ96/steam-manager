"""End-to-end user journeys through the config TUI (slow lane, marked `tui`).

Where `test_tui.py` exercises single interactions, these tests walk the same
paths a real user walks — discoverable flows only (Enter on a game, the `e`
Settings hub), never the quick-key aliases — and verify the OUTCOME on disk:
the saved `policies.toml` content, the untouched Steam files, and the state a
fresh session reloads. The usability tests assert on the exported screenshot,
i.e. on what the user actually sees at the minimum supported terminal size.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from steam_manager.cli import _wizard_core as core
from tests.tui_helpers import make_app, wait_for_screen

pytestmark = pytest.mark.tui

TOOL_TECH = "GE-Proton9-27"


@pytest.fixture
def env(env: Path, fake_steam: Path) -> Path:
    """The shared `env` (conftest) plus one installed custom compat tool;
    returns the user policy path the TUI saves to."""
    tool_dir = fake_steam / "compatibilitytools.d" / TOOL_TECH
    tool_dir.mkdir(parents=True)
    (tool_dir / "compatibilitytool.vdf").write_text(
        '"compatibilitytools"\n{\n    "compat_tools"\n    {\n'
        f'        "{TOOL_TECH}"\n        {{\n'
        '            "install_path" "."\n'
        f'            "display_name" "{TOOL_TECH}"\n'
        '            "from_oslist"  "windows"\n'
        '            "to_oslist"    "linux"\n        }\n    }\n}\n'
    )
    return env


def _steam_files_snapshot(root: Path) -> dict[str, bytes]:
    return {
        "config": (root / "config" / "config.vdf").read_bytes(),
        "localconfig": (root / "userdata" / "72021823" / "config"
                        / "localconfig.vdf").read_bytes(),
    }


async def test_journey_pick_compat_tool_and_save(env, fake_steam):
    """Enter on a game → editor → compat picker → pick the installed Proton →
    Save. The override lands in policies.toml; Steam's own files stay
    byte-identical (the TUI writes policy only)."""
    from steam_manager.cli.tui.widgets import CompatPickerScreen, GameEditScreen
    before = _steam_files_snapshot(fake_steam)
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        appid = app.state.data.games[0].appid
        await pilot.press("enter")                     # game row → editor
        await wait_for_screen(pilot, app, GameEditScreen)
        await pilot.press("enter")                     # first entry: compat tool
        await wait_for_screen(pilot, app, CompatPickerScreen)
        await pilot.press("enter")                     # first enabled option = the tool
        await pilot.pause()
        assert app.state.pending_count == 1
        await pilot.press("s")                         # Save
        await pilot.pause()
        assert app.state.pending_count == 0

    saved = tomllib.loads(env.read_text())
    assert saved["overrides"][appid]["compat_tool"] == TOOL_TECH
    assert _steam_files_snapshot(fake_steam) == before


async def test_journey_launch_options_and_reload(env):
    """Enter on a game → editor → launch options → type a command → Save.
    A brand-new session (fresh load_state) sees the persisted value with an
    empty pending queue."""
    from textual.widgets import Input
    from steam_manager.cli.tui.widgets import GameEditScreen, LaunchPickerScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        appid = app.state.data.games[0].appid
        await pilot.press("enter")
        await wait_for_screen(pilot, app, GameEditScreen)
        await pilot.press("down", "enter")             # second entry: launch options
        await wait_for_screen(pilot, app, LaunchPickerScreen)
        app.screen.query_one("#launch-input", Input).value = "mangohud %command%"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

    saved = tomllib.loads(env.read_text())
    assert saved["overrides"][appid]["launch_options"] == "mangohud %command%"

    fresh = core.load_state()
    assert fresh.pending == ()
    assert fresh.effective(f"overrides.{appid}.launch_options") == "mangohud %command%"


async def test_journey_settings_hub_target_users(env):
    """`e` → Settings hub → Target users → "All local accounts" → Save writes
    general.target_users = ["*"]."""
    from steam_manager.cli.tui.widgets import SettingsScreen, TargetUsersScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await wait_for_screen(pilot, app, SettingsScreen)
        await pilot.press(*(["down"] * 4), "enter")    # fifth entry: Target users
        await wait_for_screen(pilot, app, TargetUsersScreen)
        await pilot.press("down", "enter")             # second mode: All local accounts
        await pilot.pause()
        assert app.state.pending_count == 1
        await pilot.press("s")
        await pilot.pause()

    saved = tomllib.loads(env.read_text())
    assert saved["general"]["target_users"] == ["*"]


def _visible_text(svg: str) -> str:
    """Text content of an exported SVG screenshot, whitespace-normalized:
    the SVG splits words across text runs and uses `&#160;` entities, so
    matching is reliable only with all whitespace stripped."""
    import html
    text = "".join(re.findall(r">([^<>]+)<", svg))
    return re.sub(r"\s+", "", html.unescape(text))


def _assert_visible(label: str, text: str, where: str) -> None:
    assert label.replace(" ", "") in text, f"{label!r} not visible {where}"


async def test_usability_footer_complete_at_80x24(env):
    """Every visible action fits in the footer at the smallest supported
    terminal (80×24): a user on a tiny terminal can still discover Edit,
    Save, and Quit without reading the docs."""
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        text = _visible_text(app.export_screenshot())
    for label in ("Edit", "Ignore", "Filter", "Settings",
                  "Save", "Discard", "Reset", "Quit"):
        _assert_visible(label, text, "in the footer at 80x24")


async def test_usability_game_editor_shows_current_values(env):
    """The per-game editor is self-describing: it shows the game's name and
    its current compat/launch values, so the user never edits blind."""
    from steam_manager.cli.tui.widgets import GameEditScreen
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        game = app.state.data.games[0]
        await pilot.press("enter")
        await wait_for_screen(pilot, app, GameEditScreen)
        text = _visible_text(app.export_screenshot())
        _assert_visible(game.name, text, "in the game editor")
        _assert_visible("Compat tool", text, "in the game editor")
        _assert_visible("Launch options", text, "in the game editor")
        _assert_visible("Ignore", text, "in the game editor")
