"""Tests for the `steam-manager shortcuts` sub-command."""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import vdf
from typer.testing import CliRunner

from steam_manager import cli

runner = CliRunner()


SAMPLE_SHORTCUTS = {
    "shortcuts": {
        "0": {
            "appid": -1234567890,
            "AppName": "Heroic Games Launcher",
            "Exe": '"/usr/bin/heroic"',
            "StartDir": '"/home/me/"',
            "icon": "",
            "ShortcutPath": "",
            "LaunchOptions": "",
            "IsHidden": 0,
            "AllowDesktopConfig": 1,
            "AllowOverlay": 1,
            "OpenVR": 0,
            "Devkit": 0,
            "DevkitGameID": "",
            "DevkitOverrideAppID": 0,
            "LastPlayTime": 1715000000,
            "FlatpakAppID": "",
            "tags": {},
        }
    }
}


@pytest.fixture
def fake_steam_with_shortcuts(fake_steam: Path, tmp_path: Path, monkeypatch) -> Path:
    """`fake_steam` plus a synthetic binary shortcuts.vdf for user 72021823."""
    user_config = fake_steam / "userdata" / "72021823" / "config"
    sc_path = user_config / "shortcuts.vdf"
    with sc_path.open("wb") as f:
        vdf.binary_dump(SAMPLE_SHORTCUTS, f)
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")  # bypass Steam-running check
    return sc_path


def test_shortcuts_path_prints_user_file(fake_steam_with_shortcuts: Path):
    result = runner.invoke(cli.app, ["shortcuts", "path"])
    assert result.exit_code == 0
    assert str(fake_steam_with_shortcuts) in result.stdout


def test_shortcuts_show_prints_json(fake_steam_with_shortcuts: Path):
    result = runner.invoke(cli.app, ["shortcuts", "show"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["shortcuts"]["0"]["AppName"] == "Heroic Games Launcher"
    assert payload["shortcuts"]["0"]["LastPlayTime"] == 1715000000


def test_shortcuts_show_warns_when_file_missing(fake_steam: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")
    result = runner.invoke(cli.app, ["shortcuts", "show"])
    assert result.exit_code == 0
    assert "No shortcuts.vdf" in result.stdout


def test_shortcuts_edit_errors_when_file_missing(fake_steam: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")
    result = runner.invoke(cli.app, ["shortcuts", "edit"])
    assert result.exit_code != 0
    assert "Add a non-Steam game" in result.stdout


def test_shortcuts_edit_roundtrips_through_editor(
    fake_steam_with_shortcuts: Path, tmp_path: Path, monkeypatch
):
    """Editor modifies LaunchOptions; result must round-trip back into binary VDF
    with the new value, and a checkpoint backup must exist."""
    new_opts = "gamemoderun %command%"
    editor = tmp_path / "fake_editor.py"
    editor.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "p = sys.argv[1]\n"
        "with open(p) as f: d = json.load(f)\n"
        f"d['shortcuts']['0']['LaunchOptions'] = {new_opts!r}\n"
        "with open(p, 'w') as f: json.dump(d, f, indent=2)\n"
    )
    editor.chmod(editor.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("EDITOR", str(editor))

    result = runner.invoke(cli.app, ["shortcuts", "edit"])
    assert result.exit_code == 0, result.stdout

    # File was written: re-read the binary and verify.
    with fake_steam_with_shortcuts.open("rb") as f:
        rewritten = vdf.binary_load(f)
    assert rewritten["shortcuts"]["0"]["LaunchOptions"] == new_opts
    # Type preservation: appid must still be int (not str).
    assert isinstance(rewritten["shortcuts"]["0"]["appid"], int)
    assert rewritten["shortcuts"]["0"]["appid"] == -1234567890

    # A checkpoint .tar.gz must have been created.
    backup_root = Path(__import__("os").environ["STEAM_MANAGER_BACKUP_ROOT"])
    archives = list(backup_root.glob("*.tar.gz"))
    assert len(archives) == 1


def test_shortcuts_edit_no_changes_skips_write(
    fake_steam_with_shortcuts: Path, tmp_path: Path, monkeypatch
):
    """Editor exits without modifications: original file untouched, no backup."""
    editor = tmp_path / "noop_editor.sh"
    editor.write_text("#!/usr/bin/env bash\n: \"$1\"\n")  # no-op, doesn't write
    editor.chmod(editor.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("EDITOR", str(editor))

    # Capture original bytes for byte-level comparison.
    before = fake_steam_with_shortcuts.read_bytes()

    result = runner.invoke(cli.app, ["shortcuts", "edit"])
    assert result.exit_code == 0
    assert "No changes" in result.stdout

    after = fake_steam_with_shortcuts.read_bytes()
    assert before == after

    backup_root = Path(__import__("os").environ["STEAM_MANAGER_BACKUP_ROOT"])
    assert not list(backup_root.glob("*.tar.gz"))


def test_shortcuts_user_flag_targets_named_account(
    fake_steam_with_shortcuts: Path, tmp_path: Path, monkeypatch
):
    """--user testuser must resolve to the active fixture account."""
    result = runner.invoke(cli.app, ["shortcuts", "path", "--user", "testuser"])
    assert result.exit_code == 0
    assert "72021823" in result.stdout
