"""Backward-compat shim — re-exports the io/ public surface.

Legacy callers do `from steam_manager import steam` and reach for
`steam.discover()`, `steam.get_compat_tool()`, etc. The actual code now
lives under `steam_manager.io.{discovery,config_vdf,localconfig_vdf}`.
This file lets the rest of the refactor proceed without rewriting every
`steam.X` call site at once; once the cli/ split is complete, each call
site will import from io/ directly and this shim will be deleted.
"""
from __future__ import annotations

from steam_manager.io.config_vdf import (
    _config_vdf_path,
    _load_compat_map,
    clear_all_compat,
    get_compat_tool,
    set_compat_tool,
)
from steam_manager.io.discovery import (
    DEFAULT_STEAM_ROOT,
    STEAMID64_BASE,
    discover,
    library_label,
    list_apps,
    list_users,
)
from steam_manager.io.localconfig_vdf import (
    _load_apps_section,
    _localconfig_path,
    clear_all_launch_options,
    get_launch_options,
    set_launch_options,
)
from steam_manager.models import SteamApp, SteamContext, SteamUser

__all__ = [
    "SteamApp", "SteamContext", "SteamUser",
    "DEFAULT_STEAM_ROOT", "STEAMID64_BASE",
    "discover", "library_label", "list_apps", "list_users",
    "get_compat_tool", "set_compat_tool", "clear_all_compat",
    "get_launch_options", "set_launch_options", "clear_all_launch_options",
]
