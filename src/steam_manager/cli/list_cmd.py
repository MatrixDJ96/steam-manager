"""`steam-manager list` — show every installed game with its current config."""
from __future__ import annotations

import json as _json

import typer
from rich.console import Console

from steam_manager import policy, render
from steam_manager.cli.app import app
from steam_manager.cli import _appinfo
from steam_manager.cli._appinfo import is_listable
from steam_manager.cli._common import ExitCode, policy_paths, steam_root
from steam_manager.cli._drift import compute_drift
from steam_manager.cli._targets import (
    effective_target_spec,
    resolve_target_users,
    target_users_banner,
)
from steam_manager.io import config_vdf, discovery, localconfig_vdf


@app.command(name="list")
def list_cmd(
    user: str | None = typer.Option(
        None, "--user",
        help="Show launch options for only this account",
    ),
    all_users: bool = typer.Option(
        False, "--all-users",
        help="Show launch options for all local accounts",
    ),
    json_out: bool = typer.Option(False, "--json", help="Output JSON instead of table"),
):
    """List all installed games with compat tool and per-user launch options."""
    ctx = discovery.discover(steam_root=steam_root())
    apps = sorted(discovery.list_apps(ctx), key=lambda a: a.name.lower())
    types = _appinfo.appinfo_types()
    listable = [a for a in apps if a.installed and is_listable(a, types)]

    users_list = discovery.list_users(ctx)
    engine = policy.load(policy_paths())
    target_spec = effective_target_spec(engine.target_users, user, all_users)
    target_users = resolve_target_users(users_list, target_spec)

    if json_out:
        payload = []
        for a in listable:
            entry = {
                "appid": a.appid,
                "name": a.name,
                "library": discovery.library_label(ctx, a.library),
                "library_path": str(a.library),
                "compat_tool": config_vdf.get_compat_tool(ctx, a.appid),
                "launch_options": {
                    u.account_name: localconfig_vdf.get_launch_options(u, a.appid)
                    for u in target_users
                },
            }
            payload.append(entry)
        typer.echo(_json.dumps(payload, indent=2, ensure_ascii=False))
        raise typer.Exit(ExitCode.OK)

    render.info(target_users_banner(users_list, target_spec))

    # Same width cap as the other tables so wide terminals don't stretch
    # the list past readable bounds (see render.effective_max_width).
    console = Console(width=render.effective_max_width())
    table = render._make_inner_table()
    # AppID rendered as a clickable link to the Proton compatdata folder.
    # Name rendered as a clickable link to the game's install folder.
    table.add_column("AppID", justify="right", style="bold cyan", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("CompatTool", no_wrap=True)
    multi_user = len(target_users) > 1
    for u in target_users:
        col_name = (f"Launch ([cyan]{u.account_name}[/cyan])"
                    if multi_user else "LaunchOptions")
        table.add_column(col_name, no_wrap=True, overflow="ellipsis")

    drift_changes = compute_drift(ctx, listable, users_list, engine, target_spec)
    drift_appids = {c["appid"] for c in drift_changes}

    for a in listable:
        compat = config_vdf.get_compat_tool(ctx, a.appid) or "[dim]<none>[/dim]"
        appid_cell = render.link_cell(str(a.compatdata_path), a.appid)
        name_cell = render.link_cell(str(a.install_path), a.name)
        row = [appid_cell, name_cell, compat]
        for u in target_users:
            lo = localconfig_vdf.get_launch_options(u, a.appid) or "[dim]<none>[/dim]"
            row.append(lo)
        row_style = "bold" if a.appid in drift_appids else "dim"
        table.add_row(*row, style=row_style)

    console.print(render._panel(table, "Installed games"))
    raise typer.Exit(ExitCode.OK)
