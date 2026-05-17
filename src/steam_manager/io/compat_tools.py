"""Discovery of installed Steam compatibility tools (Proton, GE-Proton, ...).

Two sources feed the picker:

1. **User-installed custom tools** under `<steam_root>/compatibilitytools.d/`,
   each in its own directory with a `compatibilitytool.vdf` manifest. This is
   where GE-Proton, Proton-CachyOS, Pyroveil, etc. live.

2. **Official Proton builds** installed by Steam itself as regular apps. They
   appear as `appmanifest_*.acf` files whose `name` starts with "Proton".
   The tech name (what goes into `CompatToolMapping[appid].name` inside
   Steam's `config.vdf`) is derived from the human name with a small known
   mapping plus a heuristic fallback.

The tech name is the only value Steam recognises: writing a human-friendly
display name into the policy silently fails. The picker in `cli/_wizard.py`
shows display names but always emits tech names.
"""
from __future__ import annotations

import re
from pathlib import Path

import vdf

from steam_manager.io._vdf_util import ci_get
from steam_manager.io.discovery import list_apps
from steam_manager.models import CompatTool, SteamContext  # noqa: F401  (used in annotations), SteamContext

# Known official Proton builds whose tech_name doesn't follow the
# `proton_<major>` pattern. Keep this list small — anything that matches
# `_VERSIONED_PROTON_RE` is handled programmatically.
_OFFICIAL_PROTON_NAME_MAP: dict[str, str] = {
    "Proton Experimental": "proton_experimental",
    "Proton Hotfix": "proton_hotfix",
    "Proton Next": "proton_next",
    "Proton EasyAntiCheat Runtime": "proton_eac_runtime",
    "Proton BattlEye Runtime": "proton_battleye_runtime",
}

# "Proton 9.0 (Beta)", "Proton 8.0", "Proton 7.0", ...
_VERSIONED_PROTON_RE = re.compile(r"^Proton (\d+)\.\d+(?:\s|$)")

# Tools that are NOT usable as a per-game compat_tool for Windows titles.
# These exist on disk because Steam ships them as compat tools internally
# (Linux Runtime layers, anti-cheat runtimes invoked by Proton itself),
# but selecting them as a game's compat_tool is never what the user wants.
_NOT_RUNNABLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Legacy runtime", re.IGNORECASE),
    re.compile(r"^Steam Linux Runtime", re.IGNORECASE),
    # Sub-runtimes invoked by Proton (EAC/BattlEye). Matches "Proton
    # EasyAntiCheat Runtime", "Proton BattlEye Runtime", etc.
    re.compile(r"Runtime$", re.IGNORECASE),
)


def _is_runnable(tool: CompatTool) -> bool:
    """True if `tool` is a Proton/Wine-style compat tool selectable by users.

    Filters out the Steam Linux Runtime layers and the EAC/BattlEye
    sub-runtimes that Steam installs alongside the real Proton builds.
    """
    for pat in _NOT_RUNNABLE_PATTERNS:
        if pat.search(tool.display_name):
            return False
    return True


def _tech_name_for_official(name: str) -> str:
    """Derive Steam's internal compat_tool name from the human Proton app name.

    Known exact-match names use the hardcoded map; versioned names follow the
    `proton_<major>` convention. Anything else falls back to a slugified form
    — useful as a best-effort handle even if Steam may not accept it.
    """
    if name in _OFFICIAL_PROTON_NAME_MAP:
        return _OFFICIAL_PROTON_NAME_MAP[name]
    m = _VERSIONED_PROTON_RE.match(name)
    if m:
        return f"proton_{m.group(1)}"
    return name.lower().replace(" ", "_")


def parse_compatibilitytool_vdf(path: Path) -> list[CompatTool]:
    """Parse one `compatibilitytool.vdf` file into the CompatTool entries it declares.

    A single file can declare multiple tools (rare but allowed). The top-level
    layout is `compatibilitytools.compat_tools.<tech_name>` and the only field
    we read is `display_name`; everything else (install_path, from_oslist...)
    is metadata not needed by the picker.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            data = vdf.load(fh)
    except (OSError, SyntaxError, ValueError):
        return []

    root = ci_get(data, "compatibilitytools") or {}
    tools = ci_get(root, "compat_tools") or {}
    if not isinstance(tools, dict):
        return []

    out: list[CompatTool] = []
    install_dir = path.parent
    for tech_name, entry in tools.items():
        if not isinstance(entry, dict):
            continue
        display = entry.get("display_name") or tech_name
        out.append(CompatTool(
            tech_name=tech_name,
            display_name=str(display),
            source="custom",
            install_path=install_dir,
        ))
    return out


def _list_custom_tools(steam_root: Path) -> list[CompatTool]:
    """Walk `<steam_root>/compatibilitytools.d/` and parse each tool's VDF."""
    base = steam_root / "compatibilitytools.d"
    if not base.is_dir():
        return []
    out: list[CompatTool] = []
    for sub in sorted(base.iterdir()):
        if not sub.is_dir():
            continue
        manifest = sub / "compatibilitytool.vdf"
        if manifest.is_file():
            out.extend(parse_compatibilitytool_vdf(manifest))
    return out


def _list_official_proton(ctx: SteamContext) -> list[CompatTool]:
    """Find Proton builds installed by Steam by filtering appmanifest by name."""
    out: list[CompatTool] = []
    seen: set[str] = set()
    for app in list_apps(ctx):
        if not app.name.startswith("Proton"):
            continue
        tech = _tech_name_for_official(app.name)
        if tech in seen:
            continue
        seen.add(tech)
        out.append(CompatTool(
            tech_name=tech,
            display_name=app.name,
            source="official",
            install_path=app.install_path if app.installed else None,
        ))
    return out


def list_compat_tools(ctx: SteamContext, *, runnable_only: bool = True) -> list[CompatTool]:
    """Enumerate every compat tool installed on the system.

    Order: custom tools first (alphabetical by display name), then official
    Proton builds (also alphabetical by display name). The picker in
    `cli/_wizard.py` shows them in this order so user-managed tools take
    visual precedence over Steam's defaults.

    With `runnable_only=True` (the default), entries that aren't selectable
    as a game's compat_tool are filtered out — see `_is_runnable` for the
    exclusion rules. Pass `runnable_only=False` for diagnostics / debugging.
    """
    custom = sorted(_list_custom_tools(ctx.root), key=lambda t: t.display_name.lower())
    official = sorted(_list_official_proton(ctx), key=lambda t: t.display_name.lower())
    tools = custom + official
    if runnable_only:
        tools = [t for t in tools if _is_runnable(t)]
    return tools
