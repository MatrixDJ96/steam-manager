"""Read/write of the user `policies.toml` file (`~/.config/steam-manager/`).

`tomlkit` (not stdlib `tomllib`) is used because writes must preserve user
comments. The bundled factory `policies.toml` ships inside the package and
is read read-only via `importlib.resources` so it works equally in editable
installs, wheels, and the PyInstaller `_MEIPASS` bundle.

User override path can be overridden via STEAM_MANAGER_USER_POLICY (used
by tests). The CLI-side helper `cli/_common.py` re-exports USER_POLICY_PATH.

This module also owns the pure TOML manipulation helpers (`set_dotted`,
`unset_dotted`, `get_dotted`, `render_effective_doc`) used by both
`cli/config_cmd.py` and `cli/_wizard.py`. Keeping them here removes the
duplication that previously existed across the two callers and avoids the
lazy-import cycle the wizard had to use to reach into `config_cmd.py`.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import tomlkit

DEFAULT_USER_POLICY_PATH = Path.home() / ".config" / "steam-manager" / "policies.toml"


def user_path() -> Path:
    """Resolve the user policy file path, honoring STEAM_MANAGER_USER_POLICY."""
    override = os.environ.get("STEAM_MANAGER_USER_POLICY")
    return Path(override) if override else DEFAULT_USER_POLICY_PATH


def load_doc() -> tomlkit.TOMLDocument:
    """Read and parse the user policy file. Returns an empty document if absent."""
    path = user_path()
    if not path.exists():
        return tomlkit.document()
    return tomlkit.parse(path.read_text())


def save_doc(doc: tomlkit.TOMLDocument) -> None:
    """Atomic write: tmp file + os.replace, then chmod 0600.

    The user policy file may carry sensitive `launch_options` (custom
    env vars, API keys, Wine prefix tokens), so it's owner-readable only.
    """
    path = user_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(tomlkit.dumps(doc))
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def validate_toml(text: str) -> Exception | None:
    """Return the parse error if `text` is not valid TOML, else None."""
    try:
        tomllib.loads(text)
        return None
    except tomllib.TOMLDecodeError as exc:
        return exc


def _split_dotted(key: str) -> list[str]:
    parts = [p for p in key.split(".") if p]
    if not parts:
        raise ValueError(f"empty key: {key!r}")
    return parts


def get_dotted(doc: tomlkit.TOMLDocument, key: str) -> Any | None:
    """Read the value at a dotted key. Returns None if any segment is missing
    or if a non-table segment is traversed."""
    node: Any = doc
    for part in _split_dotted(key):
        if not isinstance(node, (dict, tomlkit.items.Table)) or part not in node:
            return None
        node = node[part]
    return node


def set_dotted(doc: tomlkit.TOMLDocument, key: str, value: Any) -> None:
    """Set the value at a dotted key, creating intermediate tables as needed."""
    parts = _split_dotted(key)
    node: Any = doc
    for part in parts[:-1]:
        if part not in node:
            node[part] = tomlkit.table()
        node = node[part]
    node[parts[-1]] = value


def unset_dotted(doc: tomlkit.TOMLDocument, key: str) -> bool:
    """Remove the value at a dotted key. Walks up dropping parent tables that
    become empty (a section with no remaining keys disappears from the file).

    Returns True if the key existed and was removed, False otherwise.
    """
    parts = _split_dotted(key)
    chain: list[tuple[Any, str]] = []
    node: Any = doc
    for part in parts[:-1]:
        if part not in node:
            return False
        chain.append((node, part))
        node = node[part]
    if parts[-1] not in node:
        return False
    del node[parts[-1]]
    for parent, name in reversed(chain):
        candidate = parent[name]
        if isinstance(candidate, (tomlkit.items.Table, dict)) and len(candidate) == 0:
            del parent[name]
        else:
            break
    return True


def render_effective_doc(engine: Any) -> tomlkit.TOMLDocument:
    """Render a PolicyEngine-like object as a flat TOMLDocument.

    Duck-typed on the engine (uses `max_backups`, `target_users`, `sections`,
    `overrides`) so this module stays inside the `io/` layer without
    importing from `policy.py`. Used by `config show`, `config get`, and
    the wizard's "current config" table.
    """
    out = tomlkit.document()
    general = tomlkit.table()
    general["max_backups"] = engine.max_backups
    general["target_users"] = list(engine.target_users)
    out["general"] = general
    for section_name, section in engine.sections.items():
        tbl = tomlkit.table()
        if section.compat_tool is not None:
            tbl["compat_tool"] = section.compat_tool
        if section.launch_options is not None:
            tbl["launch_options"] = section.launch_options
        out[section_name] = tbl
    if engine.overrides:
        ovr = tomlkit.table()
        for appid, fields in engine.overrides.items():
            ovr[appid] = fields
        out["overrides"] = ovr
    return out


