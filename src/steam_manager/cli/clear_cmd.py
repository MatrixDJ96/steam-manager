"""`steam-manager clear` — wipe ALL compat overrides + launch options."""
from __future__ import annotations

import typer

from steam_manager import policy, render
from steam_manager.cli._checkpoint import build_steam_files, make_checkpoint
from steam_manager.cli._common import ExitCode, policy_paths, steam_root
from steam_manager.cli._steam_guard import check_steam_closed
from steam_manager.cli._targets import (
    effective_target_spec,
    resolve_target_users,
    target_users_banner,
)
from steam_manager.cli.app import app
from steam_manager.io import config_vdf, discovery, localconfig_vdf


@app.command(name="clear")
def clear_cmd(
    user: str | None = typer.Option(
        None, "--user",
        help="Clear launch options only for this account",
    ),
    all_users: bool = typer.Option(
        False, "--all-users",
        help="Clear launch options for every local account",
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
    force: bool = typer.Option(False, "--force", help="Ignore Steam-running check"),
):
    """Wipe ALL compat tool overrides + launch options for every app.

    No filtering by app type — affects games, applications, beta, dlc, tools,
    everything Steam has a mapping for. Creates a backup checkpoint first
    so the operation is reversible via `steam-manager restore`."""
    check_steam_closed(force)

    ctx = discovery.discover(steam_root=steam_root())
    users_list = discovery.list_users(ctx)
    engine = policy.load(policy_paths())
    target_spec = effective_target_spec(engine.target_users, user, all_users)
    target_users = resolve_target_users(users_list, target_spec)

    render.info(target_users_banner(users_list, target_spec))

    # Plan summary (read-only counts so the user knows what's at stake)
    compat_count = config_vdf.count_compat_overrides(ctx)
    launch_plan = [(u, localconfig_vdf.count_launch_options(u)) for u in target_users]
    launch_total = sum(n for _, n in launch_plan)

    if compat_count == 0 and launch_total == 0:
        render.success("Nothing to clear — no compat tool or launch options set.")
        raise typer.Exit(ExitCode.OK)

    render.warning(
        f"About to clear [bold]{compat_count}[/bold] compat tool overrides "
        f"([magenta]system[/magenta]) and [bold]{launch_total}[/bold] launch "
        f"options across [bold]{len(target_users)}[/bold] user(s)."
    )
    for u, n in launch_plan:
        render.info(
            f"  [cyan]user[/cyan]:[bold cyan]{u.account_name}[/bold cyan]: "
            f"[bold]{n}[/bold] launch options"
        )

    if not yes:
        if not typer.confirm("Confirm?", default=False):
            render.info("Cancelled.")
            raise typer.Exit(ExitCode.OK)

    files, user_entries = build_steam_files(ctx, users_list)
    archive = make_checkpoint(
        trigger="clear", files=files, users=user_entries,
        max_backups=engine.max_backups,
    )
    ts = archive.name.removesuffix(".tar.gz")
    size_kb = archive.stat().st_size / 1024
    render.success(
        f"Backup checkpoint [bold cyan]{ts}[/bold cyan] created "
        f"([bold]{len(files)}[/bold] files, [dim]{size_kb:.1f} KB[/dim])"
    )

    removed_compat = config_vdf.clear_all_compat(ctx)
    if removed_compat:
        render.success(
            f"Cleared [bold]{len(removed_compat)}[/bold] compat tool overrides "
            f"([magenta]system[/magenta])"
        )

    for u in target_users:
        removed = localconfig_vdf.clear_all_launch_options(u)
        if removed:
            render.success(
                f"Cleared [bold]{len(removed)}[/bold] launch options "
                f"([cyan]user[/cyan]:[bold cyan]{u.account_name}[/bold cyan])"
            )

    render.success("All clear.")
    raise typer.Exit(ExitCode.OK)
