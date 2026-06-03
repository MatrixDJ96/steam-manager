"""Minimal parser for Steam's appinfo.vdf binary cache.

Extracts the common.type field per app (Game / DLC / Music / Demo / Tool / etc).
Used by cli.py to classify apps into policy sections (games/applications)
or to filter them out (dlc/music/tool/...).

Supports the v29 indexed format (magic 0x07564429) used by modern Steam.
Falls back gracefully (returns empty mapping) on parse error.
"""
from __future__ import annotations

import struct
from pathlib import Path

_MAGIC_V29 = 0x07564429
_MAGIC_V28 = 0x07564428
_MAGIC_V27 = 0x07564427

# Scalar KV value types and the byte width to skip past their payload:
# int32 / float32 are 4 bytes, int64 (two variants) are 8.
_SCALAR_SKIP = {0x02: 4, 0x03: 4, 0x06: 8, 0x07: 8}


def _read_string_table(data: bytes, offset: int) -> list[str]:
    """Read the v29 string index table at `offset`: a uint32 count followed by
    that many NUL-terminated UTF-8 strings. Empty list if the offset is out of
    range or the table is truncated."""
    if not (0 < offset < len(data)):
        return []
    strings: list[str] = []
    (count,) = struct.unpack_from("<I", data, offset)
    cur = offset + 4
    for _ in range(count):
        end = data.find(b"\x00", cur)
        if end < 0:
            break
        strings.append(data[cur:end].decode("utf-8", errors="replace"))
        cur = end + 1
    return strings


def parse(path: Path) -> dict[str, str]:
    """Returns {appid: type_lower} mapping. Empty dict on error."""
    try:
        with path.open("rb") as fh:
            data = fh.read()
    except OSError:
        return {}

    if len(data) < 8:
        return {}

    magic, _universe = struct.unpack_from("<II", data, 0)
    if magic not in (_MAGIC_V29, _MAGIC_V28, _MAGIC_V27):
        return {}

    # v29 has a string index table referenced by a 64-bit offset right after universe.
    string_table: list[str] = []
    cursor = 8
    if magic == _MAGIC_V29:
        (str_table_offset,) = struct.unpack_from("<Q", data, cursor)
        cursor += 8
        string_table = _read_string_table(data, str_table_offset)

    result: dict[str, str] = {}
    while cursor < len(data):
        if cursor + 4 > len(data):
            break
        (appid,) = struct.unpack_from("<I", data, cursor)
        cursor += 4
        if appid == 0:
            break

        # size (4) + state (4) + last_updated (4) + access_token (8) +
        # text_sha1 (20) + change_number (4) + binary_sha1 (20) = 64
        # Then size-64 bytes of binary KV blob.
        if cursor + 4 > len(data):
            break
        (record_size,) = struct.unpack_from("<I", data, cursor)
        cursor += 4
        record_start = cursor
        record_end = cursor + record_size
        if record_end > len(data):
            break

        # Skip header fields inside the record:
        # state(4) + last_updated(4) + access_token(8) + text_sha1(20) +
        # change_number(4) + binary_sha1(20) = 60
        kv_start = record_start + 60
        if kv_start > record_end:
            cursor = record_end
            continue

        # Parse binary KV blob, looking only for the path "appinfo.common.type"
        app_type = _extract_type(data, kv_start, record_end, string_table,
                                 indexed=(magic == _MAGIC_V29))
        if app_type:
            result[str(appid)] = app_type.lower()

        cursor = record_end

    return result


def _extract_type(buf: bytes, start: int, end: int, strings: list[str],
                  indexed: bool) -> str | None:
    """Walk the binary KV looking for common.type. Returns the value or None.
    `indexed=True` means key field is a 4-byte index into `strings` instead of
    a null-terminated string."""
    # We need to navigate: root -> 'appinfo' -> 'common' -> 'type'
    # Build a stack-based parser.

    pos = start
    path: list[str] = []

    def read_key() -> tuple[str | None, int]:
        nonlocal pos
        if indexed:
            if pos + 4 > end:
                return None, pos
            (idx,) = struct.unpack_from("<I", buf, pos)
            pos += 4
            if 0 <= idx < len(strings):
                return strings[idx], pos
            return "", pos
        # Null-terminated string
        z = buf.find(b"\x00", pos, end)
        if z < 0:
            return None, pos
        s = buf[pos:z].decode("utf-8", errors="replace")
        pos = z + 1
        return s, pos

    target = ["appinfo", "common", "type"]

    while pos < end:
        type_byte = buf[pos]
        pos += 1
        if type_byte == 0x08:
            # End of current section
            if path:
                path.pop()
            else:
                return None
            continue

        key, new_pos = read_key()
        pos = new_pos
        if key is None:
            return None

        if type_byte == 0x00:
            # Nested section
            path.append(key)
            continue

        if type_byte == 0x01:
            # String value
            z = buf.find(b"\x00", pos, end)
            if z < 0:
                return None
            value = buf[pos:z].decode("utf-8", errors="replace")
            pos = z + 1
            current = path + [key]
            if current == target:
                return value
            continue

        skip = _SCALAR_SKIP.get(type_byte)
        if skip is None:
            return None  # unknown type byte — bail
        pos += skip

    return None
