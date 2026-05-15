from pathlib import Path

import pytest

from steam_manager.io import scopebuddy


def test_observe_finds_missing_and_orphan_configs(tmp_path):
    scb_dir = tmp_path / ".config" / "scopebuddy" / "games" / "steam"
    scb_dir.mkdir(parents=True)
    (scb_dir / "111.conf").write_text("# Game One\n")
    (scb_dir / "999.conf").write_text("# Mystery\n")    # orfano

    installed_appids = ["111", "222"]
    launch_options = {"111": "scopebuddy -- %command%", "222": "scopebuddy -- %command%"}

    obs = scopebuddy.observe(scb_dir, installed_appids, launch_options)
    assert obs.games_with_scb_launch == {"111", "222"}
    assert obs.missing_configs == ["222"]   # ha scopebuddy in launch ma no file
    assert obs.orphan_configs == ["999"]    # file ma non installato


def test_init_stub_creates_file(tmp_path):
    target = tmp_path / "111.conf"
    scopebuddy.init_stub(target, "Game One")
    content = target.read_text()
    assert content.startswith("# Game One")
    assert "auto-generated" in content


def test_init_stub_raises_on_existing_no_force(tmp_path):
    target = tmp_path / "111.conf"
    target.write_text("existing")
    with pytest.raises(FileExistsError):
        scopebuddy.init_stub(target, "Game One", force=False)


def test_init_stub_overwrites_with_force(tmp_path):
    target = tmp_path / "111.conf"
    target.write_text("existing")
    scopebuddy.init_stub(target, "Game One", force=True)
    assert target.read_text().startswith("# Game One")
