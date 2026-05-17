"""`steam-manager scopebuddy` — observe and init ScopeBuddy per-game configs.

ScopeBuddy is an external tool with per-game `.conf` files under
`~/.config/scopebuddy/games/steam/<appid>.conf`. This sub-typer reports
missing/orphan configs (`scopebuddy observe`, default action) and seeds
new stubs (`scopebuddy init`). The `scb` hidden alias is registered as a
short shortcut — `scopebuddy` is the canonical name.
"""
from __future__ import annotations

import os
from pathlib import Path

import typer

from steam_manager import policy, render, steam
from steam_manager.cli import _appinfo
from steam_manager.cli._appinfo import is_listable
from steam_manager.cli._common import ExitCode, policy_paths, steam_root
from steam_manager.cli._targets import (
    effective_target_spec,
    resolve_target_users,
    target_users_banner,
)
from steam_manager.io import scopebuddy as scb_mod


def _scb_dir() -> Path:
    override = os.environ.get("STEAM_MANAGER_SCB_DIR")
    if override:
        return Path(override)
    return Path.home() / ".config" / "scopebuddy" / "games" / "steam"


scopebuddy_app = typer.Typer(help="ScopeBuddy: observe + init of base configs.")


@scopebuddy_app.callback(invoke_without_command=True)
def scb_default(
    ctx: typer.Context,
    user: str | None = typer.Option(
        None, "--user",
        help="Target only this account (overrides target_users)",
    ),
    all_users: bool = typer.Option(
        False, "--all-users",
        help="Target all local accounts",
    ),
):
    if ctx.invoked_subcommand is None:
        _scb_observe(user=user, all_users=all_users)


@scopebuddy_app.command("observe")
def scb_observe_cmd(
    user: str | None = typer.Option(
        None, "--user",
        help="Target only this account (overrides target_users)",
    ),
    all_users: bool = typer.Option(
        False, "--all-users",
        help="Target all local accounts",
    ),
):
    """Report missing/orphan ScopeBuddy configs."""
    _scb_observe(user=user, all_users=all_users)


def _scb_observe(user: str | None = None, all_users: bool = False):
    ctx = steam.discover(steam_root=steam_root())
    apps = steam.list_apps(ctx)
    users = steam.list_users(ctx)
    engine = policy.load(policy_paths())

    target_spec = effective_target_spec(engine.target_users, user, all_users)
    targets = resolve_target_users(users, target_spec)
    if not targets:
        render.error(f"No user matches {target_spec!r}.")
        raise typer.Exit(ExitCode.PARSE_ERROR)

    render.info(target_users_banner(users, target_spec))

    primary = targets[0]
    types = _appinfo.appinfo_types()
    games = [a for a in apps if a.installed and is_listable(a, types)]
    launch = {a.appid: steam.get_launch_options(primary, a.appid) for a in games}
    installed_ids = [a.appid for a in games]
    by_id = {a.appid: a for a in games}

    obs = scb_mod.observe(_scb_dir(), installed_ids, launch)

    missing_rows = sorted(
        [(
            render.link_cell(str(by_id[appid].compatdata_path), appid)
            if appid in by_id else appid,
            render.link_cell(str(by_id[appid].install_path),
                             by_id[appid].name) if appid in by_id else "?",
         )
         for appid in obs.missing_configs],
        key=lambda r: r[1].lower(),
    )
    orphan_rows = sorted(
        [(
            appid,
            render.link_cell(str(_scb_dir() / f"{appid}.conf"),
                             str(_scb_dir() / f"{appid}.conf")),
         )
         for appid in obs.orphan_configs],
        key=lambda r: (int(r[0]) if r[0].isdigit() else 10**18, r[0]),
    )

    if missing_rows:
        typer.echo(render.simple_table_str(
            f"Missing configs [bold]({len(missing_rows)})[/bold]",
            [("AppID", "right"), "Name"],
            missing_rows,
            border_style="yellow",
        ))
    if orphan_rows:
        typer.echo(render.simple_table_str(
            f"Orphan configs [bold]({len(orphan_rows)})[/bold]",
            [("AppID", "right"), "Path"],
            orphan_rows,
            border_style="yellow",
        ))

    issues = len(missing_rows) + len(orphan_rows)
    if not issues:
        render.success(
            f"All good. [bold]{len(obs.games_with_scb_launch)}[/bold] "
            f"games with scopebuddy active."
        )
    else:
        render.info(
            f"[bold]{len(obs.games_with_scb_launch)}[/bold] active, "
            f"[bold]{len(missing_rows)}[/bold] missing, "
            f"[bold]{len(orphan_rows)}[/bold] orphans."
        )

    raise typer.Exit(ExitCode.DRIFT if issues else ExitCode.OK)


@scopebuddy_app.command("init")
def scb_init_cmd(
    appid: str | None = typer.Argument(None),
    missing: bool = typer.Option(False, "--missing", help="Init all missing configs"),
    force: bool = typer.Option(False, "--force", help="Overwrite without prompting"),
    user: str | None = typer.Option(
        None, "--user",
        help="Target only this account (overrides target_users)",
    ),
    all_users: bool = typer.Option(
        False, "--all-users",
        help="Target all local accounts",
    ),
):
    """Create L1 stub for one or more games."""
    ctx = steam.discover(steam_root=steam_root())
    apps = steam.list_apps(ctx)
    types = _appinfo.appinfo_types()
    games = [a for a in apps if a.installed and is_listable(a, types)]
    by_id = {a.appid: a for a in games}

    if appid:
        targets = [appid]
    elif missing:
        users_list = steam.list_users(ctx)
        engine = policy.load(policy_paths())
        target_spec = effective_target_spec(engine.target_users, user, all_users)
        target_users = resolve_target_users(users_list, target_spec)
        if not target_users:
            render.error(f"No user matches {target_spec!r}.")
            raise typer.Exit(ExitCode.PARSE_ERROR)
        primary = target_users[0]
        launch = {a.appid: steam.get_launch_options(primary, a.appid) for a in games}
        obs = scb_mod.observe(_scb_dir(), list(by_id.keys()), launch)
        targets = obs.missing_configs
    else:
        games_sorted = sorted(games, key=lambda a: a.name.lower())
        choices = []
        all_exist = True
        for a in games_sorted:
            exists = (_scb_dir() / f"{a.appid}.conf").exists()
            if not exists:
                all_exist = False
            choices.append((a.appid, f"{a.name} ({a.appid})", exists))

        if all_exist:
            render.info("All games already have a scopebuddy config.")
            raise typer.Exit(ExitCode.OK)

        targets = render.select_apps_interactive(choices)

    if not targets:
        render.info("No games to initialize.")
        raise typer.Exit(ExitCode.OK)

    for tid in targets:
        if tid not in by_id:
            render.warning(
                f"AppID [bold]{tid}[/bold] not installed or not a game, skipping."
            )
            continue
        target_path = _scb_dir() / f"{tid}.conf"
        try:
            scb_mod.init_stub(target_path, by_id[tid].name, force=force)
            render.success(f"Created [dim]{target_path}[/dim]")
        except FileExistsError:
            render.warning(
                f"[dim]{target_path}[/dim] already exists. Use --force to overwrite."
            )

    raise typer.Exit(ExitCode.OK)
