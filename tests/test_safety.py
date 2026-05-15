import os

from steam_manager import safety


def test_steam_running_returns_none_when_no_pidfile(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "_STEAM_PID_FILE",
                        tmp_path / "nonexistent.pid")
    assert safety.steam_running() is None


def test_steam_running_returns_none_when_pid_dead(tmp_path, monkeypatch):
    pidfile = tmp_path / "steam.pid"
    pidfile.write_text("999999\n")
    monkeypatch.setattr(safety, "_STEAM_PID_FILE", pidfile)
    assert safety.steam_running() is None


def test_steam_running_returns_pid_when_alive(tmp_path, monkeypatch):
    pidfile = tmp_path / "steam.pid"
    pidfile.write_text(f"{os.getpid()}\n")
    monkeypatch.setattr(safety, "_STEAM_PID_FILE", pidfile)
    assert safety.steam_running() == os.getpid()


def test_steam_running_returns_none_on_garbage_pidfile(tmp_path, monkeypatch):
    pidfile = tmp_path / "steam.pid"
    pidfile.write_text("not-a-number\n")
    monkeypatch.setattr(safety, "_STEAM_PID_FILE", pidfile)
    assert safety.steam_running() is None
