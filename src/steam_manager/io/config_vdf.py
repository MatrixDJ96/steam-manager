"""Read/write of `config.vdf` — Steam's global config holding compat-tool mappings.

Writes go through `_atomic_write_vdf` (tmp file + `os.replace`) so a crash
mid-write can never leave a half-written `config.vdf` on disk. Steam refuses
to load a corrupt config and silently drops the entire compat-tool map; the
atomic write is the only thing that prevents that failure mode. The atomic
replace also protects against a symlinked target — `os.replace` replaces the
directory entry, it doesn't follow the symlink to overwrite an attacker-
controlled file.
"""
from __future__ import annotations

import os
from pathlib import Path

import vdf

from steam_manager.io._vdf_util import ci_get
from steam_manager.models import SteamContext


def _config_vdf_path(ctx: SteamContext) -> Path:
    return ctx.root / "config" / "config.vdf"


def _atomic_write_vdf(path: Path, data: dict) -> None:
    """Atomic VDF text write: serialize to a sibling `.tmp`, then rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        vdf.dump(data, f, pretty=True)
    os.replace(tmp, path)


def _load_compat_map(ctx: SteamContext) -> tuple[dict, dict]:
    """Return (root_data, compat_map) from
    InstallConfigStore.Software.Valve.Steam.CompatToolMapping.
    Intermediate keys are matched case-insensitively for robustness."""
    with _config_vdf_path(ctx).open(encoding="utf-8") as fh:
        data = vdf.load(fh)
    section = data
    for key in ["InstallConfigStore", "Software", "Valve", "Steam"]:
        section = ci_get(section, key)
        if section is None:
            return data, {}
    ctm_key = None
    for k in section.keys():
        if k.lower() == "compattoolmapping":
            ctm_key = k
            break
    if ctm_key is None:
        ctm_key = "CompatToolMapping"
        section[ctm_key] = {}
    return data, section[ctm_key]


def get_compat_tool(ctx: SteamContext, appid: str) -> str | None:
    _, mapping = _load_compat_map(ctx)
    entry = mapping.get(appid)
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    return name if name else None


def set_compat_tool(ctx: SteamContext, appid: str, name: str) -> None:
    data, mapping = _load_compat_map(ctx)
    existing = mapping.get(appid, {})
    if not isinstance(existing, dict):
        existing = {}
    existing.update({"name": name, "config": existing.get("config", ""),
                     "priority": existing.get("priority", "250")})
    mapping[appid] = existing
    _atomic_write_vdf(_config_vdf_path(ctx), data)


def count_compat_overrides(ctx: SteamContext) -> int:
    """Number of per-appid compat tool overrides (excluding Steam's default '0' entry)."""
    _, mapping = _load_compat_map(ctx)
    return sum(1 for k in mapping if k != "0")


def load_compat_map_from_file(path: Path) -> dict[str, dict]:
    """Read CompatToolMapping directly from a config.vdf path.

    Returns `{appid: {"name": ..., "config": ..., "priority": ...}}`. Used by
    the restore-preview to read an *archived* config.vdf without faking a
    SteamContext. On parse failure or shape mismatch returns `{}`.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            data = vdf.load(fh)
    except (OSError, SyntaxError):
        return {}
    section = data
    for key in ["InstallConfigStore", "Software", "Valve", "Steam"]:
        section = ci_get(section, key)
        if section is None:
            return {}
    for k in section.keys():
        if k.lower() == "compattoolmapping":
            return section[k] if isinstance(section[k], dict) else {}
    return {}


def clear_all_compat(ctx: SteamContext) -> list[str]:
    """Remove every per-appid entry from CompatToolMapping. Keeps the default
    entry ("0") if present (it represents Steam's global compat tool setting).
    Returns the list of appids whose mapping was removed."""
    data, mapping = _load_compat_map(ctx)
    removed = [k for k in list(mapping.keys()) if k != "0"]
    for k in removed:
        del mapping[k]
    if removed:
        _atomic_write_vdf(_config_vdf_path(ctx), data)
    return removed
