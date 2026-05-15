from steam_manager.io import appinfo


def test_parse_missing_file_returns_empty(tmp_path):
    assert appinfo.parse(tmp_path / "no.vdf") == {}


def test_parse_invalid_magic_returns_empty(tmp_path):
    f = tmp_path / "fake.vdf"
    f.write_bytes(b"\x00" * 16)
    assert appinfo.parse(f) == {}
