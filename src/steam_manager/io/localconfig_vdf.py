"""Read/write of per-user `localconfig.vdf` — holds launch options per app."""
from __future__ import annotations

from pathlib import Path

import vdf

from steam_manager.io._vdf_util import ci_get
from steam_manager.models import SteamUser


def _localconfig_path(user: SteamUser) -> Path:
    return user.userdata_dir / "config" / "localconfig.vdf"


def _load_apps_section(user: SteamUser) -> tuple[dict, dict]:
    """Return (root_data, apps_dict) from
    UserLocalConfigStore.Software.Valve.Steam.apps."""
    path = _localconfig_path(user)
    with path.open(encoding="utf-8") as fh:
        data = vdf.load(fh)
    section = data
    for key in ["UserLocalConfigStore", "Software", "Valve", "Steam"]:
        section = ci_get(section, key)
        if section is None:
            return data, {}
    apps_key = None
    for k in section.keys():
        if k.lower() == "apps":
            apps_key = k
            break
    if apps_key is None:
        apps_key = "apps"
        section[apps_key] = {}
    return data, section[apps_key]


def get_launch_options(user: SteamUser, appid: str) -> str | None:
    _, apps = _load_apps_section(user)
    entry = apps.get(appid)
    if not isinstance(entry, dict):
        return None
    return entry.get("LaunchOptions")


def set_launch_options(user: SteamUser, appid: str, opts: str) -> None:
    data, apps = _load_apps_section(user)
    entry = apps.get(appid)
    if not isinstance(entry, dict):
        entry = {}
    entry["LaunchOptions"] = opts
    apps[appid] = entry
    with _localconfig_path(user).open("w", encoding="utf-8") as f:
        vdf.dump(data, f, pretty=True)


def load_apps_section_from_file(path: Path) -> dict[str, dict]:
    """Read the apps section (with LaunchOptions etc.) directly from a
    localconfig.vdf path.

    Returns `{appid: {"LaunchOptions": ..., ...}}`. Used by the
    restore-preview to read an *archived* localconfig.vdf without faking a
    SteamUser. On parse failure or shape mismatch returns `{}`.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            data = vdf.load(fh)
    except (OSError, SyntaxError):
        return {}
    section = data
    for key in ["UserLocalConfigStore", "Software", "Valve", "Steam"]:
        section = ci_get(section, key)
        if section is None:
            return {}
    for k in section.keys():
        if k.lower() == "apps":
            return section[k] if isinstance(section[k], dict) else {}
    return {}


def clear_all_launch_options(user: SteamUser) -> list[str]:
    """Remove LaunchOptions from every app entry in this user's localconfig.
    Other fields (LastPlayed, Playtime, ...) are preserved. Returns the list
    of appids whose LaunchOptions was removed."""
    data, apps = _load_apps_section(user)
    removed: list[str] = []
    for appid, entry in apps.items():
        if isinstance(entry, dict) and "LaunchOptions" in entry:
            del entry["LaunchOptions"]
            removed.append(appid)
    if removed:
        with _localconfig_path(user).open("w", encoding="utf-8") as f:
            vdf.dump(data, f, pretty=True)
    return removed
