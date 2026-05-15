"""Steam non-Steam shortcuts: binary VDF parsing and atomic writes.

Steam stores user-added non-Steam games in a per-user binary VDF file at
`<userdata>/<sid3>/config/shortcuts.vdf`. Format differs from the text VDFs
handled in `steam.py`: values carry int32/string types explicitly rather
than being all-strings, so JSON is a safe round-trip carrier for editing
(it preserves the int-vs-string distinction; text VDF would not).
"""
from __future__ import annotations

import os
from pathlib import Path

import vdf

from steam_manager.models import ShortcutsFile, SteamUser

# Re-export ShortcutsFile so legacy imports `_shortcuts.ShortcutsFile`
# in shortcuts_cli.py keep working until that call site is updated.
__all__ = ["ShortcutsFile", "shortcuts_path", "discover", "load", "save", "validate"]


def shortcuts_path(user: SteamUser) -> Path:
    return user.userdata_dir / "config" / "shortcuts.vdf"


def discover(users: list[SteamUser]) -> list[ShortcutsFile]:
    """One ShortcutsFile per user; `exists` reflects on-disk state."""
    out: list[ShortcutsFile] = []
    for u in users:
        p = shortcuts_path(u)
        out.append(ShortcutsFile(user=u, path=p, exists=p.is_file()))
    return out


def load(path: Path) -> dict:
    """Parse the binary shortcuts.vdf into a nested dict."""
    with path.open("rb") as f:
        return vdf.binary_load(f)


def save(path: Path, data: dict) -> None:
    """Atomic write: tmp file + os.replace. Creates parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        vdf.binary_dump(data, f)
    os.replace(tmp, path)


def validate(data: dict) -> Exception | None:
    """Sanity check before writing. Permissive on inner fields (Steam adds
    new keys across versions) but strict on the outer shape."""
    if not isinstance(data, dict):
        return TypeError(f"top-level must be a dict, got {type(data).__name__}")
    sc = data.get("shortcuts")
    if sc is None:
        return ValueError("missing top-level 'shortcuts' key")
    if not isinstance(sc, dict):
        return TypeError(f"'shortcuts' must be a dict, got {type(sc).__name__}")
    for idx, entry in sc.items():
        if not isinstance(entry, dict):
            return TypeError(
                f"entry {idx!r} must be a dict, got {type(entry).__name__}"
            )
    return None
