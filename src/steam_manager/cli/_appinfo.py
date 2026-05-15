"""App-type classification helpers used by list/diff/apply.

What counts as a "game" (vs application/tool/dlc/etc.) is decided by
parsing Steam's binary `appinfo.vdf` cache for each app's `common.type`.
`policy.section_for_type()` maps that type to a policy section name.
This module wraps the lookup with an `@lru_cache` so the parse cost is
paid once per process, and provides the name-prefix fallback used when
the cache is missing or misclassifies (e.g. Proton, Steam Linux Runtime).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from steam_manager import policy
from steam_manager.io import appinfo

_APPINFO_PATH = Path.home() / ".local" / "share" / "Steam" / "appcache" / "appinfo.vdf"

NON_GAME_NAME_PREFIXES = (
    "Proton",
    "Steam Linux Runtime",
    "Steamworks Common",
    "SteamVR",
    "Source SDK",
)


@lru_cache(maxsize=1)
def appinfo_types() -> dict[str, str]:
    """Load appinfo.vdf once, return {appid: type_lower}."""
    return appinfo.parse(_APPINFO_PATH)


def is_listable(app, types_map: dict[str, str]) -> bool:
    """Same filter used by diff/apply: drops dlc/music/tool and known tool prefixes."""
    app_type = types_map.get(app.appid)
    section = policy.section_for_type(app_type)
    if section is None:
        return False
    if any(app.name.startswith(p) for p in NON_GAME_NAME_PREFIXES):
        return False
    return True
