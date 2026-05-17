"""`steam-manager open` — open install/compatdata folder via xdg-open."""
from __future__ import annotations

import subprocess

import typer

from steam_manager import render, steam
from steam_manager.cli._common import ExitCode, steam_root
from steam_manager.cli.app import app


@app.command(name="open")
def open_cmd(
    appid: str = typer.Argument(..., help="AppID of an installed game"),
    compat: bool = typer.Option(
        False, "--compat",
        help="Open the Proton compatdata folder instead of the install folder",
    ),
):
    """Open a game's install folder (or compatdata with --compat) via xdg-open."""
    ctx = steam.discover(steam_root=steam_root())
    apps = steam.list_apps(ctx)
    by_id = {a.appid: a for a in apps}
    if appid not in by_id:
        render.error(f"AppID [bold]{appid}[/bold] not installed.")
        raise typer.Exit(ExitCode.PARSE_ERROR)

    app_obj = by_id[appid]
    target = app_obj.compatdata_path if compat else app_obj.install_path
    label = "compatdata" if compat else "install"

    if not target.exists():
        if target.parent.exists():
            render.warning(
                f"{label} folder doesn't exist for [bold]{appid}[/bold]; "
                f"opening parent: [dim]{target.parent}[/dim]"
            )
            target = target.parent
        else:
            render.error(f"Path doesn't exist: [dim]{target}[/dim]")
            raise typer.Exit(ExitCode.PARSE_ERROR)

    try:
        subprocess.Popen(
            ["xdg-open", str(target)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        render.error("xdg-open not found in PATH.")
        raise typer.Exit(ExitCode.PARSE_ERROR)

    render.success(
        f"Opened [bold cyan]{label}[/bold cyan] folder of [bold]{app_obj.name}[/bold]: "
        f"[dim]{target}[/dim]"
    )
    raise typer.Exit(ExitCode.OK)
