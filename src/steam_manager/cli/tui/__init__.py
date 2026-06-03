"""Textual TUI front-end for `steam-manager config`.

The ONLY package that imports Textual (enforced by tests/test_architecture.py).
`run()` is the entry the dispatcher (`cli/_config_entry.py`) calls when the TUI
mode is selected on an interactive terminal.
"""
from __future__ import annotations


def run(ctx=None) -> int:
    """Launch the config TUI. Returns 0. The App is imported lazily so merely
    importing this package never constructs Textual."""
    from steam_manager.cli.tui.app import ConfigApp

    ConfigApp(ctx=ctx).run()
    return 0
