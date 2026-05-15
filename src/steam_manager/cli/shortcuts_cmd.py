"""`steam-manager shortcuts` sub-command: inspect and edit non-Steam shortcuts."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import typer

from steam_manager import render, steam
from steam_manager.cli._checkpoint import make_checkpoint
from steam_manager.cli._common import ExitCode, steam_root
from steam_manager.cli._editor import choose_editor
from steam_manager.cli._steam_guard import check_steam_closed
from steam_manager.io import shortcuts_vdf as _shortcuts

shortcuts_app = typer.Typer(help="Inspect and edit non-Steam game shortcuts.")


def _resolve_target(user_flag: str | None) -> tuple[steam.SteamUser, _shortcuts.ShortcutsFile]:
    """Find the user + their shortcuts.vdf. Prompts when multiple users + no flag."""
    ctx = steam.discover(steam_root=steam_root())
    users = steam.list_users(ctx)
    if not users:
        render.error("No Steam users found.")
        raise typer.Exit(ExitCode.PARSE_ERROR)

    if user_flag:
        match = next((u for u in users if u.account_name == user_flag), None)
        if match is None:
            render.error(f"No user named {user_flag!r}.")
            raise typer.Exit(ExitCode.PARSE_ERROR)
        chosen = match
    elif len(users) == 1:
        chosen = users[0]
    else:
        active = next((u for u in users if u.is_active), None)
        if active is not None:
            chosen = active
        else:
            choices = [(u.account_name, u.account_name) for u in users]
            picked = render.select_one_interactive("Select a Steam account:", choices)
            if picked is None:
                render.info("Cancelled.")
                raise typer.Exit(ExitCode.OK)
            chosen = next(u for u in users if u.account_name == picked)

    p = _shortcuts.shortcuts_path(chosen)
    return chosen, _shortcuts.ShortcutsFile(user=chosen, path=p, exists=p.is_file())


@shortcuts_app.command()
def path(
    user: str | None = typer.Option(
        None, "--user", help="Target this account (default: active or prompt)."
    ),
) -> None:
    """Print the path of the user's shortcuts.vdf."""
    _, sf = _resolve_target(user)
    typer.echo(str(sf.path))


@shortcuts_app.command()
def show(
    user: str | None = typer.Option(None, "--user", help="Target this account."),
) -> None:
    """Print the user's shortcuts.vdf as pretty JSON."""
    _, sf = _resolve_target(user)
    if not sf.exists:
        render.warning(f"No shortcuts.vdf at {sf.path} (no non-Steam games yet).")
        raise typer.Exit(ExitCode.OK)
    data = _shortcuts.load(sf.path)
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


@shortcuts_app.command()
def edit(
    user: str | None = typer.Option(None, "--user", help="Target this account."),
    force: bool = typer.Option(False, "--force", help="Ignore Steam-running check."),
) -> None:
    """Edit non-Steam shortcuts in $EDITOR. Round-trips via JSON to preserve types.

    Decodes shortcuts.vdf to JSON in a tempfile, opens $EDITOR, loops on
    invalid JSON, writes back the binary atomically. Creates a `.tar.gz`
    checkpoint of the original before writing (recoverable via `restore`).
    """
    check_steam_closed(force)
    user_obj, sf = _resolve_target(user)

    if not sf.exists:
        render.error(
            f"No shortcuts.vdf at [dim]{sf.path}[/dim].\n"
            "Add a non-Steam game from the Steam UI first."
        )
        raise typer.Exit(ExitCode.PARSE_ERROR)

    data = _shortcuts.load(sf.path)
    initial = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f"shortcuts-{user_obj.account_name}-", suffix=".json"
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    tmp_path.write_text(initial)

    editor = choose_editor()
    try:
        while True:
            subprocess.run([*editor, str(tmp_path)], check=False)
            text = tmp_path.read_text()
            try:
                new_data = json.loads(text)
            except json.JSONDecodeError as exc:
                render.error(f"JSON parse error: {exc}")
                if not typer.confirm("Re-open the editor?", default=True):
                    render.warning("Aborted; no changes written.")
                    raise typer.Exit(ExitCode.PARSE_ERROR)
                continue

            err = _shortcuts.validate(new_data)
            if err is not None:
                render.error(f"Invalid shortcuts.vdf structure: {err}")
                if not typer.confirm("Re-open the editor?", default=True):
                    render.warning("Aborted; no changes written.")
                    raise typer.Exit(ExitCode.PARSE_ERROR)
                continue

            if text == initial:
                render.warning("No changes — nothing written.")
                raise typer.Exit(ExitCode.OK)

            arch_name = f"users/{user_obj.account_name}/shortcuts.vdf"
            archive = make_checkpoint(
                trigger="shortcuts-edit",
                files={arch_name: sf.path},
                users=[user_obj.account_name],
            )
            size_kb = archive.stat().st_size / 1024
            ts_label = archive.name.removesuffix(".tar.gz")
            render.success(
                f"Backup checkpoint [bold cyan]{ts_label}[/bold cyan] "
                f"created ([dim]{size_kb:.1f} KB[/dim])"
            )

            _shortcuts.save(sf.path, new_data)
            render.success(f"Wrote [bold]{sf.path}[/bold]")
            raise typer.Exit(ExitCode.OK)
    except KeyboardInterrupt:
        render.warning("Aborted; no changes written.")
        raise typer.Exit(3)
    finally:
        tmp_path.unlink(missing_ok=True)
