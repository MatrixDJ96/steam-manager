"""`steam-manager apply` — write planned changes (auto-backup)."""
from __future__ import annotations

import typer

from steam_manager import policy, render, steam
from steam_manager.cli._checkpoint import build_steam_files, make_checkpoint
from steam_manager.cli._common import ExitCode, policy_paths, steam_root
from steam_manager.cli._drift import compute_drift
from steam_manager.cli._steam_guard import check_steam_closed
from steam_manager.cli._targets import effective_target_spec, target_users_banner
from steam_manager.cli.app import app


@app.command()
def apply(
    force: bool = typer.Option(False, "--force", help="Ignore the Steam-running check"),
    user: str | None = typer.Option(
        None, "--user",
        help="Target only this account (overrides target_users)",
    ),
    all_users: bool = typer.Option(
        False, "--all-users",
        help="Target all local accounts",
    ),
    appid: str | None = typer.Option(
        None, "--appid",
        help="Apply only to a single AppID",
    ),
):
    """Apply planned changes (auto-backup, no dry-run)."""
    check_steam_closed(force)

    ctx = steam.discover(steam_root=steam_root())
    apps = steam.list_apps(ctx)
    users = steam.list_users(ctx)
    engine = policy.load(policy_paths())

    target_spec = effective_target_spec(engine.target_users, user, all_users)
    render.info(target_users_banner(users, target_spec))

    changes = compute_drift(ctx, apps, users, engine, target_spec=target_spec)
    if appid is not None:
        changes = [c for c in changes if c["appid"] == appid]

    if not changes:
        if appid is not None:
            name = next((a.name for a in apps if a.appid == appid), None)
            label = f"[bold]{appid}[/bold]" + (f" {name}" if name else "")
            render.success(f"No changes needed for {label}.")
        else:
            render.success("No changes needed.")
        raise typer.Exit(ExitCode.OK)

    files, user_entries = build_steam_files(ctx, users)
    archive = make_checkpoint(
        trigger="apply", files=files, users=user_entries,
        max_backups=engine.max_backups,
    )
    ts = archive.name.removesuffix(".tar.gz")
    size_kb = archive.stat().st_size / 1024
    render.success(
        f"Backup checkpoint [bold cyan]{ts}[/bold cyan] created "
        f"([bold]{len(files)}[/bold] files, [dim]{size_kb:.1f} KB[/dim])"
    )

    users_by_name = {u.account_name: u for u in users}
    for c in changes:
        if c["field"] == "compat_tool":
            steam.set_compat_tool(ctx, c["appid"], c["new"])
            render.success(
                f"[bold]{c['appid']}[/bold]  {c['name']}: "
                f"[bold]compat_tool[/bold] updated"
            )
        elif c["field"] == "launch_options":
            user = users_by_name[c["user"]]
            steam.set_launch_options(user, c["appid"], c["new"])
            render.success(
                f"[bold]{c['appid']}[/bold]  {c['name']}: "
                f"[bold]launch_options[/bold] updated "
                f"([cyan]user[/cyan]:[bold cyan]{c['user']}[/bold cyan])"
            )

    render.success(f"[bold]{len(changes)}[/bold] changes applied.")
    raise typer.Exit(ExitCode.OK)
