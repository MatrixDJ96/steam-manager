"""`steam-manager config` sub-command: edit and inspect the user policy file.

Surface is intentionally small:

  - `config` (no sub-command) → launches the interactive `wizard` (the
    default UX for editing the policy).
  - `config wizard` → same, explicit form.
  - `config get <key>` / `config set <key> <value>` / `config unset <key>` →
    scriptable primitives over dotted keys (factory + user merged for get;
    user-only for set/unset). Type inference on `set`: `true`/`false` → bool,
    digits → int, else string.
  - `config path` → prints the resolved path of the user policy file
    (handy for `cat $(steam-manager config path)` or
    `$EDITOR $(steam-manager config path)`).

Show, edit, reset, and ignore are NOT sub-commands of their own:

  - show → covered by the wizard's "Show current configuration" entry.
  - edit → handled by `$EDITOR $(steam-manager config path)`.
  - reset → `rm $(steam-manager config path)` or the wizard's
    "Reset to defaults" entry.
  - ignore <appid> → covered by the wizard's "Toggle ignore list" entry
    or by `config set overrides.<appid>.ignore true`.
"""
from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Any

import tomlkit
import typer

from steam_manager.io import policies_toml

config_app = typer.Typer(
    help="Edit and inspect the user policy file (default: launch wizard).",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _infer_value(raw: str) -> Any:
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    return raw


def _merged_doc() -> tomlkit.TOMLDocument:
    """Render the effective config (factory + user overrides).

    Honors STEAM_MANAGER_POLICY_PATHS for tests; used by `get`.
    """
    from steam_manager import policy
    factory = Path(str(files("steam_manager").joinpath("policies.toml")))
    override = os.environ.get("STEAM_MANAGER_POLICY_PATHS")
    if override:
        paths = [Path(p) for p in override.split(":") if p]
    else:
        paths = [factory, policies_toml.user_path()]
    engine = policy.load(paths)
    return policies_toml.render_effective_doc(engine)


@config_app.callback()
def config_callback(
    ctx: typer.Context,
    classic: bool = typer.Option(
        False, "--classic/--no-classic",
        help="Use the classic prompt-based wizard instead of the TUI.",
    ),
    tui: bool = typer.Option(
        False, "--tui/--no-tui",
        help="Use the full-screen Textual TUI.",
    ),
) -> None:
    """Default entry: `steam-manager config` with no sub-command opens the
    interactive editor (Textual TUI or the classic wizard)."""
    if ctx.invoked_subcommand is None:
        from steam_manager.cli import _config_entry
        _config_entry.dispatch(classic=classic, tui=tui)


@config_app.command()
def wizard(
    classic: bool = typer.Option(
        False, "--classic/--no-classic",
        help="Use the classic prompt-based wizard instead of the TUI.",
    ),
    tui: bool = typer.Option(
        False, "--tui/--no-tui",
        help="Use the full-screen Textual TUI.",
    ),
) -> None:
    """Open the interactive config editor (explicit form of bare `config`)."""
    from steam_manager.cli import _config_entry
    _config_entry.dispatch(classic=classic, tui=tui)


@config_app.command()
def path() -> None:
    """Print the path of the user policy file."""
    typer.echo(str(policies_toml.user_path()))


@config_app.command()
def get(key: str) -> None:
    """Print the effective value at a dotted key (factory plus your overrides)."""
    value = policies_toml.get_dotted(_merged_doc(), key)
    if value is None:
        typer.secho(f"key not found: {key}", fg="red", err=True)
        raise typer.Exit(3)
    if isinstance(value, (tomlkit.items.Table, dict)):
        leaf = key.split(".")[-1]
        typer.echo(tomlkit.dumps({leaf: value}).rstrip())
    else:
        typer.echo(str(value))


@config_app.command(name="set")
def set_(key: str, value: str) -> None:
    """Set a dotted key. Type inference: true/false → bool, digits → int, else string."""
    doc = policies_toml.load_doc()
    inferred = _infer_value(value)
    policies_toml.set_dotted(doc, key, inferred)
    policies_toml.save_doc(doc)
    typer.secho(f"Set {key} = {inferred!r}", fg="green")


@config_app.command()
def unset(key: str) -> None:
    """Remove a dotted key. Drops the parent table if it becomes empty."""
    doc = policies_toml.load_doc()
    if not policies_toml.unset_dotted(doc, key):
        typer.secho(f"key not found: {key}", fg="red", err=True)
        raise typer.Exit(3)
    policies_toml.save_doc(doc)
    typer.secho(f"Unset {key}", fg="green")
