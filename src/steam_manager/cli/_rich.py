"""rich-click integration: align Options/Commands first-column widths.

Typer renders --help via its own rich code path, which auto-sizes panel
columns by content. That makes the Options first column (long "--option"
names) end at a different position than the Commands first column (short
verb names), so descriptions don't visually align.

We disable Typer's rich mode at the Typer() call site
(`rich_markup_mode=None`) and let rich-click format help instead.
rich-click doesn't expose a per-panel first-column min-width option, so
this module monkey-patches RichOptionPanel.get_table / RichCommandPanel.get_table
to force a fixed first-column width on both, then gives the *last* column
ratio=1 so it absorbs the remaining space — which keeps the help text
starting at the same column position in both panels.

`install_rich_click(app)` must be called exactly once before the first
CLI dispatch. `main()` in `cli/__init__.py` does this.
"""
from __future__ import annotations

from steam_manager import render

# Width (in columns) of the first column in both Options and Commands panels.
# Picked to comfortably fit "--all-users" (the widest top-level option name)
# plus a couple of spaces before the description.
_HELP_FIRST_COL_WIDTH = 14


def install_rich_click(app):
    """Re-class the Click command tree to rich-click's RichGroup/RichCommand
    and patch their table builders to align the first-column width across the
    Options and Commands panels. Returns the prepared Click group."""
    import rich_click
    import rich_click.rich_command as _rc
    import rich_click.rich_panel as _rp

    rich_click.rich_click.COMMAND_GROUPS = {
        "steam-manager": [
            {"name": "Inspect", "commands": ["list", "diff"]},
            {"name": "Apply", "commands": ["apply", "clear"]},
            {"name": "Backup", "commands": ["backup", "restore"]},
            {"name": "Steam tools", "commands": ["scopebuddy", "shortcuts", "open"]},
            {"name": "Manage", "commands": ["config", "update"]},
        ],
    }

    rich_click.rich_click.PADDING_ERRORS_SUGGESTION = (0, 1, 1, 1)
    rich_click.rich_click.PADDING_ERRORS_PANEL = (0, 0, 0, 0)

    rich_click.rich_click.MAX_WIDTH = render.effective_max_width()

    if not getattr(_rp, "_steam_manager_aligned", False):
        _orig_opt_get_table = _rp.RichOptionPanel.get_table
        _orig_cmd_get_table = _rp.RichCommandPanel.get_table

        def _align_columns(table, width: int) -> None:
            if not table.columns:
                return
            col0 = table.columns[0]
            col0.width = width
            col0.min_width = width
            col0.max_width = width
            col0.ratio = None
            col0.no_wrap = True
            for c in table.columns[1:-1]:
                c.ratio = None
                c.width = None
                c.min_width = None
                c.max_width = None
            if len(table.columns) > 1:
                last = table.columns[-1]
                last.ratio = 1
                last.width = None
                last.min_width = None
                last.max_width = None

        def _opt_get_table(self, command, ctx, formatter):
            table = _orig_opt_get_table(self, command, ctx, formatter)
            _align_columns(table, _HELP_FIRST_COL_WIDTH)
            return table

        def _cmd_get_table(self, command, ctx, formatter):
            table = _orig_cmd_get_table(self, command, ctx, formatter)
            _align_columns(table, _HELP_FIRST_COL_WIDTH)
            return table

        _rp.RichOptionPanel.get_table = _opt_get_table
        _rp.RichCommandPanel.get_table = _cmd_get_table
        _rp._steam_manager_aligned = True

    import typer.main
    click_app = typer.main.get_command(app)

    def _make_rich_command(cmd) -> None:
        panel = getattr(cmd, "rich_help_panel", None) or getattr(cmd, "panel", None)
        cmd.__class__ = _rc.RichCommand
        cmd.panel = panel
        cmd.panels = []
        cmd.aliases = []
        if not hasattr(cmd, "_help_option"):
            cmd._help_option = None

    def _make_rich_group(grp) -> None:
        _make_rich_command(grp)
        grp.__class__ = _rc.RichGroup
        grp._alias_mapping = {}
        grp._panel_command_mapping = {}
        for sub in grp.commands.values():
            if hasattr(sub, "commands"):
                _make_rich_group(sub)
            else:
                _make_rich_command(sub)
        for sub in grp.commands.values():
            if sub.name and getattr(sub, "panel", None):
                grp.add_command_to_panel(sub, sub.panel)

    _make_rich_group(click_app)
    return click_app
