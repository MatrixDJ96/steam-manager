"""Drift computation: compare on-disk state to the resolved policy.

Used by `list` (to mark drifting rows bold), `diff` (the read-only
preview), and `apply` (which writes the drift away). The list of
returned change dicts is the manifest format consumed by `restore` —
keep it stable.
"""
from __future__ import annotations

from steam_manager import policy, steam
from steam_manager.cli import _appinfo
from steam_manager.cli._appinfo import NON_GAME_NAME_PREFIXES
from steam_manager.cli._targets import resolve_target_users
from steam_manager.models import SteamApp, SteamContext, SteamUser


def compute_drift(
    ctx: SteamContext,
    apps: list[SteamApp],
    users: list[SteamUser],
    engine: policy.PolicyEngine,
    target_spec: list[str] | None = None,
) -> list[dict]:
    """Return the list of planned changes vs the resolved policy.

    Each change dict has: appid, name, compatdata_path, install_path,
    field ('compat_tool' | 'launch_options'), old, new, user (None for
    system-wide compat_tool changes, account_name for per-user options).
    """
    changes: list[dict] = []
    spec = target_spec if target_spec is not None else engine.target_users
    targets = resolve_target_users(users, spec)
    apps = sorted(apps, key=lambda a: a.name.lower())
    types = _appinfo.appinfo_types()
    for app in apps:
        if not app.installed:
            continue
        app_type = types.get(app.appid)
        pol = policy.resolve(engine, app.appid, app_type)
        if pol is None or pol.ignore:
            continue
        if any(app.name.startswith(p) for p in NON_GAME_NAME_PREFIXES):
            continue

        compatdata_path = str(app.compatdata_path)
        install_path = str(app.install_path)

        if pol.compat_tool:
            current_compat = steam.get_compat_tool(ctx, app.appid)
            if current_compat != pol.compat_tool:
                changes.append({
                    "appid": app.appid, "name": app.name,
                    "compatdata_path": compatdata_path,
                    "install_path": install_path,
                    "field": "compat_tool", "old": current_compat,
                    "new": pol.compat_tool, "user": None,
                })

        if pol.launch_options:
            for user in targets:
                current_launch = steam.get_launch_options(user, app.appid)
                if current_launch != pol.launch_options:
                    changes.append({
                        "appid": app.appid, "name": app.name,
                        "compatdata_path": compatdata_path,
                        "install_path": install_path,
                        "field": "launch_options", "old": current_launch,
                        "new": pol.launch_options, "user": user.account_name,
                    })
    return changes
