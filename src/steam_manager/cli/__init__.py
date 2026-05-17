"""CLI entry point: assembles the Typer `app` and exposes `main()`.

Layout follows the pip/pipx convention: each top-level command lives in its
own `<verb>_cmd.py` module (list, diff, apply, clear, open, backup, restore)
and each sub-typer family lives in `<name>_cmd.py` (config, shortcuts, scb).
Every command registers itself via the `@app.command()` decorator at import
time; this module imports each module purely for that side effect.

Dependency rules (see CLAUDE.md / docs/ARCHITECTURE.md):
- cli/ imports from io/, policy, safety, render, models — never the reverse
- io/ is import-free of CLI concerns
- _helpers (cli/_*.py) may import each other; *_cmd.py modules import them
"""
from __future__ import annotations

from steam_manager.cli._common import (  # re-export for tests + backward compat
    ExitCode,
    USER_POLICY_PATH,
    backup_root,
    iso_timestamp,
    policy_paths,
    steam_root,
    update_state_path,
)
from steam_manager.cli._rich import install_rich_click
from steam_manager.cli.app import app

# Backward-compat underscore aliases. Tests and (until step 10) some
# sibling modules still import `_steam_root`, `_backup_root`, etc. directly
# from `steam_manager.cli`. These aliases keep those callers working.
_steam_root = steam_root
_policy_paths = policy_paths
_backup_root = backup_root
_iso_timestamp = iso_timestamp


# --- Register top-level commands by importing their modules -----------------
#
# Each *_cmd module's @app.command() decorator runs at import time, attaching
# the command to `app`. Alphabetical order for readability; dispatch doesn't
# care.
from steam_manager.cli import (  # noqa: E402, F401  side-effect imports
    apply_cmd,
    backup_cmd,
    clear_cmd,
    diff_cmd,
    list_cmd,
    open_cmd,
    restore_cmd,
    update_cmd,
)

# --- Register sub-typer families -------------------------------------------
from steam_manager.cli.config_cmd import config_app  # noqa: E402
from steam_manager.cli.scopebuddy_cmd import scopebuddy_app  # noqa: E402
from steam_manager.cli.shortcuts_cmd import shortcuts_app  # noqa: E402

app.add_typer(config_app, name="config")
app.add_typer(scopebuddy_app, name="scopebuddy")
app.add_typer(shortcuts_app, name="shortcuts")

# Short hidden aliases (functional, omitted from `--help`).
app.add_typer(scopebuddy_app, name="scb", hidden=True)
app.add_typer(shortcuts_app, name="sct", hidden=True)


def main() -> None:
    """Entry point. Installs rich-click formatting then dispatches the CLI.

    A `result_callback` runs the passive update notifier after every command
    exits (including non-zero typer.Exit codes). Uncaught Python exceptions
    skip the callback — which is desired: don't spam a notifier when the user
    has a real problem.
    """
    import sys
    click_app = install_rich_click(app)

    @click_app.result_callback()
    def _post_dispatch(result, **kwargs):
        from steam_manager.cli._update_check import run_post_command_hook
        # Best-effort: first non-flag arg from argv is the invoked sub-command.
        invoked = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        run_post_command_hook(invoked)
        return result

    click_app()
