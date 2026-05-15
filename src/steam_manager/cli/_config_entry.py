"""Dispatch for `config` / `config wizard`: choose the Textual TUI, the classic
questionary flow, or refuse and point at the scriptable primitives.

The single decision point. It keeps Textual out of the command module: the
`cli.tui` package is imported lazily, only when the TUI is the chosen mode and
the terminal is interactive — so `--version`, `list`, `config get`, and any
non-TTY invocation never load Textual.
"""
from __future__ import annotations

import sys

import typer

from steam_manager.cli._common import config_ui_mode

# Built-in default when neither a flag nor STEAM_MANAGER_CONFIG_UI is set.
# `--classic` (or STEAM_MANAGER_CONFIG_UI=classic) is the escape hatch to the
# prompt-based wizard for exotic terminals.
_DEFAULT_MODE = "tui"


def _ui_is_interactive() -> bool:
    """True only when both stdin and stdout are real TTYs. A full-screen UI
    (questionary or Textual) needs a live terminal on both ends; a pipe or a
    captured StringIO (CliRunner) is not interactive."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _resolve_mode(classic: bool, tui: bool) -> str:
    """Precedence: explicit flag > STEAM_MANAGER_CONFIG_UI > built-in default."""
    if classic:
        return "classic"
    if tui:
        return "tui"
    return config_ui_mode() or _DEFAULT_MODE


def _non_tty_hint() -> None:
    """Point at the scriptable escape hatch on stderr (no UI in a dead pipe)."""
    typer.echo(
        "config needs an interactive terminal. Use the scriptable primitives:\n"
        "  steam-manager config get <key>\n"
        "  steam-manager config set <key> <value>\n"
        "  steam-manager config unset <key>\n"
        '  steam-manager config path   # then: $EDITOR "$(steam-manager config path)"',
        err=True,
    )


def dispatch(*, classic: bool = False, tui: bool = False) -> None:
    """Entry called by `config` (no subcommand) and `config wizard`.

    Non-TTY → print the scriptable hint and exit 2 (never spin a UI into a dead
    pipe). A Textual startup failure (bad $TERM, driver error, missing dep)
    falls through to the same hint + exit 2 rather than wedging the terminal.
    """
    if classic and tui:
        raise typer.BadParameter("--classic and --tui are mutually exclusive")
    if not _ui_is_interactive():
        _non_tty_hint()
        raise typer.Exit(2)

    if _resolve_mode(classic, tui) == "tui":
        try:
            from steam_manager.cli import tui as _tui
            _tui.run()
            return
        except typer.Exit:
            raise
        except Exception:  # noqa: BLE001 — never wedge the terminal on a TUI failure
            _non_tty_hint()
            raise typer.Exit(2)

    from steam_manager.cli import _wizard
    _wizard.run()
