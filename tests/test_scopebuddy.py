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


def test_observe_local_conf_shadowed_by_its_base(tmp_path):
    """<appid>.local.conf is an override of <appid>.conf: when the base file
    exists the local one is invisible — never an orphan, never a separate
    entry (regression: it used to show as orphan '<appid>.local')."""
    scb_dir = tmp_path / "scb"
    scb_dir.mkdir()
    (scb_dir / "111.conf").write_text("# base\n")
    (scb_dir / "111.local.conf").write_text("# local override\n")

    obs = scopebuddy.observe(scb_dir, ["111"], {"111": "scopebuddy -- %command%"})
    assert obs.missing_configs == []
    assert obs.orphan_configs == []


def test_observe_local_conf_without_base_surfaces(tmp_path):
    """A dangling local override (no base config) stays visible: the game's
    base config still counts as missing and the '<appid>.local' entry shows
    so the anomaly is actionable."""
    scb_dir = tmp_path / "scb"
    scb_dir.mkdir()
    (scb_dir / "111.local.conf").write_text("# local without base\n")

    obs = scopebuddy.observe(scb_dir, ["111"], {"111": "scopebuddy -- %command%"})
    assert obs.missing_configs == ["111"]
    assert obs.orphan_configs == ["111.local"]


def test_observe_local_conf_of_uninstalled_game(tmp_path):
    """Base + local of an uninstalled game: only the base is the orphan; the
    shadowed local never doubles the row."""
    scb_dir = tmp_path / "scb"
    scb_dir.mkdir()
    (scb_dir / "999.conf").write_text("# base\n")
    (scb_dir / "999.local.conf").write_text("# local\n")

    obs = scopebuddy.observe(scb_dir, ["111"], {"111": None})
    assert obs.orphan_configs == ["999"]
