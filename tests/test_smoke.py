"""Smoke test: la libreria vdf riesce a parsare i fixture."""
from pathlib import Path

import vdf

FIXTURES = Path(__file__).parent / "fixtures"


def test_vdf_parses_libraryfolders():
    data = vdf.load((FIXTURES / "libraryfolders.vdf").open(encoding="utf-8"))
    assert "libraryfolders" in data
    assert data["libraryfolders"]["0"]["path"] == "/tmp/fake-steam"
    assert data["libraryfolders"]["1"]["path"] == "/tmp/fake-steam-disk2"


def test_vdf_parses_loginusers():
    data = vdf.load((FIXTURES / "loginusers.vdf").open(encoding="utf-8"))
    assert "76561198032287551" in data["users"]
    assert data["users"]["76561198032287551"]["AccountName"] == "testuser"
    assert data["users"]["76561198032287551"]["MostRecent"] == "1"
