"""Unit tests for the pure ScopeBuddy dashboard core (cli/_scb_core.py)."""
from __future__ import annotations

from pathlib import Path

from steam_manager.cli import _scb_core as core
from steam_manager.models import SteamApp


def _game(appid: str, name: str, tmp_path: Path) -> SteamApp:
    """Minimal installed SteamApp (state_flags=4 -> installed)."""
    return SteamApp(appid=appid, name=name, library=tmp_path, state_flags=4)


def test_load_rows_classifies_all_states(tmp_path):
    scb = tmp_path / "scb"; scb.mkdir()
    (scb / "111.conf").write_text("x")      # active (launch has scopebuddy)
    (scb / "999.conf").write_text("x")      # orphan (no installed game)
    games = [_game("111", "Alpha", tmp_path), _game("222", "Beta", tmp_path),
             _game("333", "Gamma", tmp_path)]
    launch = {"111": "scopebuddy -- %command%", "222": "scopebuddy -- %command%",
              "333": "mangohud %command%"}
    rows = core.load_rows(scb, games, launch)
    by_id = {r.appid: r for r in rows}
    assert by_id["111"].status == "active"
    assert by_id["222"].status == "missing"
    assert by_id["333"].status == "inactive"
    assert by_id["999"].status == "orphan" and by_id["999"].name == "999.conf"
    assert [r.appid for r in rows] == ["111", "222", "333", "999"]  # name-sorted + orphans


def test_load_rows_row_shape(tmp_path):
    scb = tmp_path / "scb"; scb.mkdir()
    games = [_game("111", "Alpha", tmp_path)]
    rows = core.load_rows(scb, games, {})
    row = rows[0]
    assert row.name == "Alpha"
    assert row.conf_path == scb / "111.conf"
    assert row.install_path == str(games[0].install_path)
    assert row.compatdata_path == str(games[0].compatdata_path)


def test_load_rows_orphan_row_shape(tmp_path):
    scb = tmp_path / "scb"; scb.mkdir()
    (scb / "abc.conf").write_text("x")
    rows = core.load_rows(scb, [], {})
    row = rows[0]
    assert row.appid == "abc"
    assert row.name == "abc.conf"
    assert row.status == "orphan"
    assert row.conf_path == scb / "abc.conf"
    assert row.install_path == "" and row.compatdata_path == ""


def test_load_rows_sorts_games_case_insensitively(tmp_path):
    scb = tmp_path / "scb"; scb.mkdir()
    games = [_game("1", "zeta", tmp_path), _game("2", "Alpha", tmp_path),
             _game("3", "mike", tmp_path)]
    rows = core.load_rows(scb, games, {})
    assert [r.name for r in rows] == ["Alpha", "mike", "zeta"]


def test_load_rows_orphans_sorted_by_stem(tmp_path):
    scb = tmp_path / "scb"; scb.mkdir()
    for stem in ("777", "222", "555"):
        (scb / f"{stem}.conf").write_text("x")
    rows = core.load_rows(scb, [], {})
    assert [r.appid for r in rows] == ["222", "555", "777"]
