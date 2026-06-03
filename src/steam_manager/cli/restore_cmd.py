"""`steam-manager restore` — roll back to a previous checkpoint."""
from __future__ import annotations

import re
from pathlib import Path

import typer

from steam_manager import render
from steam_manager.cli._common import ExitCode, backup_root, steam_root
from steam_manager.cli._restore_diff import compute_restore_diff
from steam_manager.cli._steam_guard import check_steam_closed
from steam_manager.cli.app import app
from steam_manager.io import backups, discovery
from steam_manager.models import SteamContext, SteamUser


# Steam account names are ASCII alphanumeric plus a few safe punctuation
# characters. We use this as a defence-in-depth check on values coming out
# of a checkpoint manifest before they're interpolated into a filesystem
# path — a malicious manifest with `"users": ["../../../etc/cron.d/x"]`
# would otherwise let `restore` write archive content to attacker-chosen
# locations. Length cap 64 chars (Steam's own limit is well below this).
_VALID_UNAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _user_localconfig_archname(name: str) -> str | None:
    """Return the account name embedded in `users/<account>/localconfig.vdf`,
    or None if `name` doesn't match that exact shape."""
    parts = name.split("/")
    if (
        len(parts) == 3
        and parts[0] == "users"
        and parts[2] == "localconfig.vdf"
        and _VALID_UNAME.fullmatch(parts[1])
    ):
        return parts[1]
    return None


def _checkpoint_summary(c: dict) -> str:
    """One-line description of a checkpoint: which system/user files it holds.

    Reads the manifest's user list, falling back to scanning the archive
    member names when the manifest carries none."""
    parts: list[str] = []
    if c["manifest"].get("system"):
        parts.append("[magenta]system[/magenta]")
    for uname in c["manifest"].get("users", []):
        if _VALID_UNAME.fullmatch(str(uname)):
            parts.append(f"[cyan]user[/cyan]:[bold cyan]{uname}[/bold cyan]")
    if not parts:
        for name in c["files"]:
            if name == "config.vdf":
                parts.append("[magenta]system[/magenta]")
            else:
                uname = _user_localconfig_archname(name)
                if uname is not None:
                    parts.append(f"[cyan]user[/cyan]:[bold cyan]{uname}[/bold cyan]")
    return ", ".join(parts) if parts else "[dim](empty)[/dim]"


def _resolve_restore_targets(
    chosen: dict, ctx: SteamContext,
) -> tuple[dict[str, Path], dict[str, SteamUser]]:
    """Map archive members to their on-disk destinations for a restore.

    Returns the `{archive_name: dest_path}` dict the extractor consumes plus
    the `{account_name: SteamUser}` map of local accounts. Candidate user names
    come from the manifest, falling back to the archive member names; each is
    validated against `_VALID_UNAME` and every destination is confined to the
    Steam root — defence-in-depth so a malicious manifest can't smuggle a
    path-traversal token through a symlinked userdata dir. Unsafe or unknown
    users are warned about and skipped.
    """
    targets: dict[str, Path] = {}
    ctx_root_resolved = ctx.root.resolve()
    if chosen["manifest"].get("system") or "config.vdf" in chosen["files"]:
        targets["config.vdf"] = ctx.root / "config" / "config.vdf"

    raw_unames: list[str] = list(chosen["manifest"].get("users", []))
    if not raw_unames:
        for name in chosen["files"]:
            uname = _user_localconfig_archname(name)
            if uname is not None:
                raw_unames.append(uname)

    all_users = {u.account_name: u for u in discovery.list_users(ctx)}
    for uname in raw_unames:
        if not _VALID_UNAME.fullmatch(str(uname)):
            render.warning(f"Skipping malformed user name in checkpoint: {uname!r}")
            continue
        if uname not in all_users:
            render.warning(
                f"User '{uname}' in checkpoint but no longer exists locally, skipping."
            )
            continue
        dest = all_users[uname].userdata_dir / "config" / "localconfig.vdf"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.resolve().is_relative_to(ctx_root_resolved):
                raise ValueError(f"destination outside Steam root: {dest}")
        except (OSError, ValueError) as exc:
            render.warning(f"Refusing to restore {uname}: {exc}")
            continue
        targets[f"users/{uname}/localconfig.vdf"] = dest
    return targets, all_users


@app.command()
def restore(
    last: bool = typer.Option(False, "--last", help="Restore the latest checkpoint"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
    force: bool = typer.Option(False, "--force", help="Ignore Steam-running check"),
):
    """Restore a previous checkpoint archive (config.vdf + every user's localconfig.vdf)."""
    check_steam_closed(force)

    ctx = discovery.discover(steam_root=steam_root())
    root = backup_root()

    checkpoints = backups.list_checkpoints(root)
    if not checkpoints:
        render.warning("No backups available.")
        raise typer.Exit(ExitCode.OK)

    checkpoints_desc = list(reversed(checkpoints))

    if last:
        chosen = checkpoints_desc[0]
    else:
        choices = [
            (f"{c['timestamp']}    ({render.strip_markup(_checkpoint_summary(c))})", str(i))
            for i, c in enumerate(checkpoints_desc)
        ]
        idx = render.select_one_interactive(
            "Select checkpoint to restore:", choices,
        )
        if idx is None:
            render.info("No checkpoint selected.")
            raise typer.Exit(ExitCode.OK)
        chosen = checkpoints_desc[int(idx)]

    targets, all_users = _resolve_restore_targets(chosen, ctx)

    # Compute the diff on-the-fly: what would actually change on disk if we
    # extracted this archive? Empty diff means the archive is identical to
    # the live state — skip the extraction entirely (it would be a no-op).
    # Only consider users whose targets passed validation above.
    valid_unames = [
        _user_localconfig_archname(n) for n in targets
        if _user_localconfig_archname(n) is not None
    ]
    users_list = list(all_users.values())
    diff = compute_restore_diff(
        Path(chosen["path"]), ctx, users_list, valid_unames,
    )

    if not diff:
        render.success(
            f"Checkpoint [bold cyan]{chosen['timestamp']}[/bold cyan] "
            "would change nothing — already in this state."
        )
        raise typer.Exit(ExitCode.OK)

    render.info(
        f"Restoring checkpoint [bold cyan]{chosen['timestamp']}[/bold cyan] "
        f"({_checkpoint_summary(chosen)}) would apply [bold]{len(diff)}[/bold] change(s):"
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
        uname = _user_localconfig_archname(name)
        if uname is not None:
            render.success(
                f"Restored [bold]localconfig.vdf[/bold] "
                f"([cyan]user[/cyan]:[bold cyan]{uname}[/bold cyan])"
            )

    render.success(
        f"Checkpoint [bold cyan]{chosen['timestamp']}[/bold cyan] restored "
        f"([bold]{len(extracted)}[/bold] files)."
    )
    raise typer.Exit(ExitCode.OK)
