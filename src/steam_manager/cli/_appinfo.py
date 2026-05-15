"""App-type classification helpers used by list/diff/apply.

What counts as a "game" (vs application/tool/dlc/etc.) is decided by
parsing Steam's binary `appinfo.vdf` cache for each app's `common.type`.
`policy.section_for_type()` maps that type to a policy section name.
This module caches the parse on the resolved Steam-root path so the parse
cost is paid once per (root, process), and provides the name-prefix
fallback used when the cache is missing or misclassifies (e.g. Proton,
Steam Linux Runtime).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from steam_manager import policy
from steam_manager.cli._common import steam_root as _steam_root
from steam_manager.io import appinfo

NON_GAME_NAME_PREFIXES = (
    "Proton",
    "Steam Linux Runtime",
    "Steamworks Common",
    "SteamVR",
    "Source SDK",
)


def _default_steam_root() -> Path:
    return Path.home() / ".local" / "share" / "Steam"


@lru_cache(maxsize=4)
def _parse_for_root(root: Path) -> dict[str, str]:
    return appinfo.parse(root / "appcache" / "appinfo.vdf")


def appinfo_types() -> dict[str, str]:
    """Load appinfo.vdf, honoring STEAM_MANAGER_STEAM_ROOT.

    Cached on the resolved root so a test that sets
    STEAM_MANAGER_STEAM_ROOT=/tmp/fake_steam doesn't see the *real* user's
    appinfo cache (which would silently misclassify the fixture's apps
    and mask `is_listable` regressions). Production hits the cache on
    the second call.
    """
    root = _steam_root() or _default_steam_root()
    return _parse_for_root(root)


def is_listable(app, types_map: dict[str, str]) -> bool:
    """Same filter used by diff/apply: drops dlc/music/tool and known tool prefixes."""
    app_type = types_map.get(app.appid)
    section = policy.section_for_type(app_type)
    if section is None:
        return False
    if any(app.name.startswith(p) for p in NON_GAME_NAME_PREFIXES):
        return False
    return True
