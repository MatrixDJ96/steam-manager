"""`steam-manager diff` — preview planned changes vs policy (read-only)."""
from __future__ import annotations

import typer

from steam_manager import policy, render, steam
from steam_manager.cli._common import ExitCode, policy_paths, steam_root
from steam_manager.cli._drift import compute_drift
from steam_manager.cli._targets import effective_target_spec, target_users_banner
from steam_manager.cli.app import app


@app.command()
def diff(
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
        help="Restrict to a single AppID",
    ),
):
    """Show changes that `apply` would make (read-only)."""
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
            render.success(f"No drift for {label} — already conforms to policy.")
        else:
            render.success("No drift, everything conforms to policy.")
        raise typer.Exit(ExitCode.OK)

    typer.echo(render.diff_table_str(changes))
    render.info(
        f"[bold]{len(changes)}[/bold] changes planned. "
        f"Run `steam-manager apply` to apply."
    )
    raise typer.Exit(ExitCode.DRIFT)
