"""Steam installation discovery: libraryfolders.vdf, loginusers.vdf, appmanifest_*.acf."""
from __future__ import annotations

from pathlib import Path

import vdf

from steam_manager.models import SteamApp, SteamContext, SteamUser

DEFAULT_STEAM_ROOT = Path.home() / ".local" / "share" / "Steam"
STEAMID64_BASE = 76561197960265728


def discover(steam_root: Path | None = None) -> SteamContext:
    """Find Steam library folders. Users and apps are loaded elsewhere."""
    root = steam_root or DEFAULT_STEAM_ROOT
    if not root.is_dir():
        raise FileNotFoundError(f"Steam root not found at {root}")

    libfile = root / "steamapps" / "libraryfolders.vdf"
    with libfile.open(encoding="utf-8") as fh:
        data = vdf.load(fh)
    libs = data.get("libraryfolders", {})

    libraries: list[Path] = []
    labels: dict[str, str] = {}
    for _, entry in libs.items():
        path = entry.get("path")
        if not path:
            continue
        libraries.append(Path(path))
        # `label` may be missing on the default library — fall back to "Linux"
        # for the steam root, else use the directory name.
        lbl = entry.get("label")
        if not lbl:
            if str(Path(path).resolve()) == str(root.resolve()):
                lbl = "Linux"
            else:
                lbl = Path(path).name or path
        labels[path] = lbl

    return SteamContext(root=root, libraries=libraries, library_labels=labels)


def library_label(ctx: SteamContext, path: Path) -> str:
    """Return the library label for a given app library Path. Falls back to dir name."""
    key = str(path)
    if key in ctx.library_labels:
        return ctx.library_labels[key]
    resolved = str(path.resolve())
    for k, v in ctx.library_labels.items():
        if str(Path(k).resolve()) == resolved:
            return v
    return path.name or str(path)


def list_apps(ctx: SteamContext) -> list[SteamApp]:
    """Enumerate apps by scanning appmanifest_*.acf in every library."""
    apps: list[SteamApp] = []
    for lib in ctx.libraries:
        steamapps = lib / "steamapps"
        if not steamapps.is_dir():
            continue
        for acf in steamapps.glob("appmanifest_*.acf"):
            with acf.open(encoding="utf-8") as fh:
                data = vdf.load(fh)
            state = data.get("AppState", {})
            appid = state.get("appid")
            if not appid:
                continue
            try:
                flags = int(state.get("StateFlags", "0"))
            except ValueError:
                flags = 0
            apps.append(SteamApp(
                appid=appid,
                name=state.get("name", "?"),
                library=lib,
                state_flags=flags,
                installdir=state.get("installdir", ""),
            ))
    return apps


def list_users(ctx: SteamContext) -> list[SteamUser]:
    """Read loginusers.vdf and return one SteamUser per local account."""
    loginfile = ctx.root / "config" / "loginusers.vdf"
    with loginfile.open(encoding="utf-8") as fh:
        data = vdf.load(fh)
    raw = data.get("users", {})

    users: list[SteamUser] = []
    for steamid64, entry in raw.items():
        sid3 = str(int(steamid64) - STEAMID64_BASE)
        users.append(SteamUser(
            account_name=entry.get("AccountName", ""),
            steamid64=steamid64,
            steamid3=sid3,
            userdata_dir=ctx.root / "userdata" / sid3,
            is_active=entry.get("MostRecent") == "1",
        ))
    return users
