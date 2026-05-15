"""`steam-manager restore` — roll back to a previous checkpoint."""
from __future__ import annotations

from pathlib import Path

import typer

from steam_manager import render, steam
from steam_manager.cli._common import ExitCode, backup_root, steam_root
from steam_manager.cli._restore_diff import compute_restore_diff
from steam_manager.cli._steam_guard import check_steam_closed
from steam_manager.cli.app import app
from steam_manager.io import backups


@app.command()
def restore(
    last: bool = typer.Option(False, "--last", help="Restore the latest checkpoint"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
    force: bool = typer.Option(False, "--force", help="Ignore Steam-running check"),
):
    """Restore a previous checkpoint archive (config.vdf + every user's localconfig.vdf)."""
    check_steam_closed(force)

    ctx = steam.discover(steam_root=steam_root())
    root = backup_root()

    checkpoints = backups.list_checkpoints(root)
    if not checkpoints:
        render.warning("No backups available.")
        raise typer.Exit(ExitCode.OK)

    def _summary(c: dict) -> str:
        parts: list[str] = []
        if c["manifest"].get("system"):
            parts.append("[magenta]system[/magenta]")
        for uname in c["manifest"].get("users", []):
            parts.append(
                f"[cyan]user[/cyan]:[bold cyan]{uname}[/bold cyan]"
            )
        if not parts:
            for name in c["files"]:
                if name == "config.vdf":
                    parts.append("[magenta]system[/magenta]")
                elif name.startswith("users/") and name.endswith("/localconfig.vdf"):
                    uname = name.split("/")[1]
                    parts.append(
                        f"[cyan]user[/cyan]:[bold cyan]{uname}[/bold cyan]"
                    )
        return ", ".join(parts) if parts else "[dim](empty)[/dim]"

    checkpoints_desc = list(reversed(checkpoints))

    if last:
        chosen = checkpoints_desc[0]
    else:
        choices = [
            (f"{c['timestamp']}    ({render.strip_markup(_summary(c))})", str(i))
            for i, c in enumerate(checkpoints_desc)
        ]
        idx = render.select_one_interactive(
            "Select checkpoint to restore:", choices,
        )
        if idx is None:
            render.info("No checkpoint selected.")
            raise typer.Exit(ExitCode.OK)
        chosen = checkpoints_desc[int(idx)]

    targets: dict[str, Path] = {}
    if chosen["manifest"].get("system") or "config.vdf" in chosen["files"]:
        targets["config.vdf"] = ctx.root / "config" / "config.vdf"

    users_present = list(chosen["manifest"].get("users", []))
    if not users_present:
        for name in chosen["files"]:
            if name.startswith("users/") and name.endswith("/localconfig.vdf"):
                users_present.append(name.split("/")[1])

    all_users = {u.account_name: u for u in steam.list_users(ctx)}
    for uname in users_present:
        if uname not in all_users:
            render.warning(
                f"User '{uname}' in checkpoint but no longer exists locally, skipping."
            )
            continue
        arch_name = f"users/{uname}/localconfig.vdf"
        targets[arch_name] = all_users[uname].userdata_dir / "config" / "localconfig.vdf"

    # Compute the diff on-the-fly: what would actually change on disk if we
    # extracted this archive? Empty diff means the archive is identical to
    # the live state — skip the extraction entirely (it would be a no-op).
    users_list = list(all_users.values())
    diff = compute_restore_diff(
        Path(chosen["path"]), ctx, users_list, users_present,
    )

    if not diff:
        render.success(
            f"Checkpoint [bold cyan]{chosen['timestamp']}[/bold cyan] "
            "would change nothing — already in this state."
        )
        raise typer.Exit(ExitCode.OK)

    render.info(
        f"Restoring checkpoint [bold cyan]{chosen['timestamp']}[/bold cyan] "
        f"({_summary(chosen)}) would apply [bold]{len(diff)}[/bold] change(s):"
    )
    typer.echo(render.diff_table_str(diff))

    if not yes:
        if not typer.confirm(
            f"Restore {len(targets)} file(s)?", default=False,
        ):
            render.info("Cancelled.")
            raise typer.Exit(ExitCode.OK)

    render.info(
        f"Restoring checkpoint [bold cyan]{chosen['timestamp']}[/bold cyan]..."
    )
    extracted = backups.extract_checkpoint(Path(chosen["path"]), targets)

    if "config.vdf" in extracted:
        render.success("Restored [bold]config.vdf[/bold] ([magenta]system[/magenta])")
    for name in extracted:
        if name.startswith("users/") and name.endswith("/localconfig.vdf"):
            uname = name.split("/")[1]
            render.success(
                f"Restored [bold]localconfig.vdf[/bold] "
                f"([cyan]user[/cyan]:[bold cyan]{uname}[/bold cyan])"
            )

    render.success(
        f"Checkpoint [bold cyan]{chosen['timestamp']}[/bold cyan] restored "
        f"([bold]{len(extracted)}[/bold] files)."
    )
    raise typer.Exit(ExitCode.OK)
