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


def test_delete_config_removes_file(tmp_path):
    from steam_manager.io import scopebuddy
    conf = tmp_path / "123.conf"
    conf.write_text("# stub\n")
    scopebuddy.delete_config(conf)
    assert not conf.exists()


def test_delete_config_missing_raises(tmp_path):
    from steam_manager.io import scopebuddy
    with pytest.raises(FileNotFoundError):
        scopebuddy.delete_config(tmp_path / "nope.conf")


def test_scb_dir_env_override(monkeypatch, tmp_path):
    from steam_manager.cli import _common
    monkeypatch.setenv("STEAM_MANAGER_SCB_DIR", str(tmp_path))
    assert _common.scb_dir() == tmp_path
