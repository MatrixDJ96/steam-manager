import struct

from steam_manager.io import appinfo


def test_parse_missing_file_returns_empty(tmp_path):
    assert appinfo.parse(tmp_path / "no.vdf") == {}


def test_parse_invalid_magic_returns_empty(tmp_path):
    f = tmp_path / "fake.vdf"
    f.write_bytes(b"\x00" * 16)
    assert appinfo.parse(f) == {}


def _v29_blob(appid: int, app_type: str) -> bytes:
    """Build a minimal v29 (indexed) appinfo.vdf with one app whose
    appinfo.common.type is `app_type`. Mirrors the format parse() expects:
    header + uint64 string-table offset + one record + appid-0 terminator +
    string table. Keys are uint32 indices into the table; the type value is a
    NUL-terminated inline string."""
    strings = ["appinfo", "common", "type"]
    kv = (
        b"\x00" + struct.pack("<I", 0)              # nested: appinfo
        + b"\x00" + struct.pack("<I", 1)            # nested: common
        + b"\x01" + struct.pack("<I", 2) + app_type.encode() + b"\x00"  # str: type
    )
    record = struct.pack("<I", appid) + struct.pack("<I", 60 + len(kv)) + b"\x00" * 60 + kv
    terminator = struct.pack("<I", 0)
    str_table = struct.pack("<I", len(strings)) + b"".join(s.encode() + b"\x00" for s in strings)
    str_table_offset = 16 + len(record) + len(terminator)
    return (struct.pack("<I", 0x07564429) + struct.pack("<I", 1)
            + struct.pack("<Q", str_table_offset) + record + terminator + str_table)


def test_parse_v29_extracts_common_type(tmp_path):
    f = tmp_path / "appinfo.vdf"
    f.write_bytes(_v29_blob(123, "game"))
    assert appinfo.parse(f) == {"123": "game"}


def test_parse_v29_lowercases_type(tmp_path):
    f = tmp_path / "appinfo.vdf"
    f.write_bytes(_v29_blob(7, "Application"))
    assert appinfo.parse(f) == {"7": "application"}
