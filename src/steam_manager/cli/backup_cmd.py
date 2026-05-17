"""`steam-manager backup` — manual full checkpoint of system + user configs."""
from __future__ import annotations

import typer

from steam_manager import policy, render
from steam_manager.cli._checkpoint import build_steam_files, make_checkpoint
from steam_manager.cli._common import ExitCode, policy_paths, steam_root
from steam_manager.cli.app import app
from steam_manager.io import discovery


@app.command()
def backup():
    """Create a full checkpoint archive (config.vdf + every user's localconfig.vdf)."""
    ctx = discovery.discover(steam_root=steam_root())
    users = discovery.list_users(ctx)
    engine = policy.load(policy_paths())

    files, user_entries = build_steam_files(ctx, users)

    render.info("Creating checkpoint...")
    if "config.vdf" in files:
        render.success("Added [bold]config.vdf[/bold] ([magenta]system[/magenta])")
    for uname in user_entries:
        render.success(
            f"Added [bold]localconfig.vdf[/bold] "
            f"([cyan]user[/cyan]:[bold cyan]{uname}[/bold cyan])"
        )

    archive = make_checkpoint(
        trigger="manual", files=files, users=user_entries,
        max_backups=engine.max_backups,
    )
    ts = archive.name.removesuffix(".tar.gz")

    size_kb = archive.stat().st_size / 1024
    render.success(
        f"Checkpoint [bold cyan]{ts}[/bold cyan] created "
        f"([bold]{len(files)}[/bold] files, [dim]{size_kb:.1f} KB[/dim])."
    )
    raise typer.Exit(ExitCode.OK)
