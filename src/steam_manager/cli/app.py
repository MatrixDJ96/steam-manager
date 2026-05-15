"""Typer `app` singleton + root callback.

Lives in its own module so command files (cli/list_cmd.py, cli/diff_cmd.py,
...) can do `from steam_manager.cli.app import app` without importing
cli/__init__.py — which would create a cycle, since __init__.py imports
the command modules to register them via their `@app.command()` decorators.

The Typer constructor disables Rich rendering so rich-click's formatter
takes over; cli/_rich.install_rich_click() rewires the Click tree at
dispatch time.
"""
from __future__ import annotations

import typer

from steam_manager import __version__

app = typer.Typer(
    help="Audit and batch-apply policies on a local Steam library.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"steam-manager {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Root callback. Keeps `app` as a multi-command group so sub-commands
    like `diff` are invoked as `steam-manager diff` rather than being
    collapsed into a single-command CLI by Typer."""
