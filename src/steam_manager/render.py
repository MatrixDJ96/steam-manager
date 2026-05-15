"""Output formatting: rich tables, success/warning/error, questionary prompts."""
from __future__ import annotations

import re
import shutil
import sys
from io import StringIO
from typing import Iterable
from urllib.parse import quote

import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def link_cell(path: str, text: str) -> str:
    """Build a Rich-markup clickable hyperlink cell pointing to a local path.

    The path is URI-encoded so file:// URLs with spaces/special chars work
    (e.g. ".../Age of Empires IV"). Terminals with OSC 8 support (Konsole,
    GNOME Terminal, Kitty, WezTerm, Alacritty, iTerm2) render this as a
    clickable region; activation usually requires Ctrl+Click in Konsole."""
    if not path:
        return text
    encoded = quote(path, safe="/:")
    return f"[link=file://{encoded}]{text}[/link]"

# Match Rich markup tags like [bold], [/bold], [bold cyan], [/]. Used to strip
# markup for output paths that don't render Rich (e.g. questionary menus).
_RICH_MARKUP_RE = re.compile(r"\[/?[^\[\]]*\]")

# Fallback when Rich can't detect terminal width (tests, piped output).
TABLE_WIDTH = 100

# Shared rounded-corner box style for every table.
TABLE_BOX = box.ROUNDED

# Border styles for the wrapping panel — semantic tones.
# `dim` matches rich-click/Typer --help panels (default, neutral).
PANEL_BORDER_STYLE = "dim"
PANEL_BORDER_WARN = "yellow"
PANEL_BORDER_DANGER = "red"
PANEL_BORDER_OK = "green"

# Shared console for normal output; tests can pass their own StringIO.
console = Console()


def _make_inner_table() -> Table:
    """Inner Table for use inside a Panel — no own box/borders, no own title.
    Per-row styling (bold/dim/...) is applied via `Table.add_row(..., style=...)`
    by callers when they have semantic info (e.g. `list` marks drift rows bold)."""
    return Table(
        show_header=True,
        header_style="bold dim",
        show_lines=False,
        box=None,
        padding=(0, 2),
        expand=True,
    )


def _panel(content, title: str, *, border_style: str = PANEL_BORDER_STYLE) -> Panel:
    """Wrap content (a Table) in a titled Panel matching rich-click/Typer --help style.
    Title is wrapped in [bold] so it pops against the dim border."""
    return Panel(
        content,
        title=f"[bold]{title}[/bold]",
        title_align="left",
        box=TABLE_BOX,
        border_style=border_style,
        padding=(0, 1),
    )


def effective_max_width() -> int:
    """Max width for tables/panels.

    - < 160 cols: use full width.
    - >= 160 cols (4K/wide): cap at half-screen, min 120, to stay readable.
    - No terminal (CliRunner, pipe): TABLE_WIDTH = 100.
    """
    cols = shutil.get_terminal_size(fallback=(0, 0)).columns
    if cols <= 0:
        return TABLE_WIDTH
    if cols < 160:
        return cols
    return max(120, cols // 2)


def _buffer_width() -> int:
    """Width for buffered Console. Historical alias of `effective_max_width`."""
    return effective_max_width()


def _stdout_is_tty() -> bool:
    """True when the final output destination (stdout) is a real terminal.
    Used by the buffer-backed Console to decide whether to emit ANSI styling
    (border colors, header bold-dim, zebra stripes) — which would otherwise
    be lost when Rich writes to a StringIO buffer."""
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def audit_table_str(rows: Iterable[tuple]) -> str:
    """Render the audit table to a string.
    Rows: (appid, name, compat_tool, launch_options, compat_ok, launch_ok)."""
    buf = StringIO()
    local = Console(file=buf, force_terminal=_stdout_is_tty(), width=_buffer_width())
    table = _make_inner_table()
    table.add_column("AppID", justify="right", style="bold cyan", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("CompatTool", no_wrap=True)
    table.add_column("LaunchOpts", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    for appid, name, compat, launch, c_ok, l_ok in rows:
        status = ("✓" if c_ok else "✗") + " " + ("✓" if l_ok else "✗")
        compat_cell = compat if compat else "[dim]<default>[/dim]"
        launch_cell = launch if launch else "[dim]<missing>[/dim]"
        table.add_row(appid, name, compat_cell, launch_cell, status)
    local.print(_panel(table, "Steam audit"))
    return buf.getvalue()


def diff_table_str(changes: list[dict]) -> str:
    """Renders diff output grouped by field type and (for launch options) by user.
    Drift is a warning state, so the wrapping panels use a yellow border.

    All sub-tables share the same column widths (computed from all changes at once)
    so the columns line up visually across the multiple panels."""
    buf = StringIO()
    local = Console(file=buf, force_terminal=_stdout_is_tty(), width=_buffer_width())

    compat_changes = [c for c in changes if c["field"] == "compat_tool"]
    launch_changes = [c for c in changes if c["field"] == "launch_options"]

    # Compute max content width per column ACROSS all sub-tables, so each table's
    # columns get the same min_width and the result lines up between panels.
    def _disp_len(v) -> int:
        return len(str(v) if v is not None else "<none>")

    all_changes = compat_changes + launch_changes
    if all_changes:
        col_min = {
            "appid": max(5, *(_disp_len(c["appid"]) for c in all_changes)),
            "name":  max(4, *(_disp_len(c["name"]) for c in all_changes)),
            "from":  max(4, *(_disp_len(c["old"]) for c in all_changes)),
            "to":    max(2, *(_disp_len(c["new"]) for c in all_changes)),
        }
    else:
        col_min = {"appid": 5, "name": 4, "from": 4, "to": 2}

    def _add_columns(t):
        t.add_column("AppID", justify="right", style="bold cyan", no_wrap=True,
                     min_width=col_min["appid"])
        t.add_column("Name", no_wrap=True, min_width=col_min["name"])
        t.add_column("From", style="red", no_wrap=True, min_width=col_min["from"])
        t.add_column("To", style="green", no_wrap=True, min_width=col_min["to"])

    if compat_changes:
        t = _make_inner_table()
        _add_columns(t)
        for c in compat_changes:
            old = c["old"] if c["old"] is not None else "[dim]<none>[/dim]"
            new = c["new"] if c["new"] is not None else "[dim]<none>[/dim]"
            appid_cell = link_cell(c.get("compatdata_path", ""), c["appid"])
            name_cell = link_cell(c.get("install_path", ""), c["name"])
            t.add_row(appid_cell, name_cell, old, new)
        local.print(_panel(t, "Compat tool", border_style=PANEL_BORDER_WARN))

    # Group launch changes by user
    by_user: dict[str, list[dict]] = {}
    for c in launch_changes:
        by_user.setdefault(c.get("user") or "-", []).append(c)

    user_count = len(by_user)
    for user, items in by_user.items():
        if user_count > 1:
            title = (
                f"Launch options [dim]—[/dim] "
                f"[cyan]user[/cyan]:[bold cyan]{user}[/bold cyan]"
            )
        else:
            title = "Launch options"
        t = _make_inner_table()
        _add_columns(t)
        for c in items:
            old = c["old"] if c["old"] is not None else "[dim]<none>[/dim]"
            new = c["new"] if c["new"] is not None else "[dim]<none>[/dim]"
            appid_cell = link_cell(c.get("compatdata_path", ""), c["appid"])
            name_cell = link_cell(c.get("install_path", ""), c["name"])
            t.add_row(appid_cell, name_cell, old, new)
        local.print(_panel(t, title, border_style=PANEL_BORDER_WARN))

    return buf.getvalue()


def _column_style(name: str) -> str | None:
    """Default per-column style for `simple_table_str`. Bold for IDs, dim for paths."""
    if name == "AppID":
        return "bold cyan"
    if name == "Path":
        return "dim"
    return None


def simple_table_str(
    title: str,
    columns: list[str | tuple[str, str]],
    rows: list[tuple],
    *,
    border_style: str = PANEL_BORDER_STYLE,
) -> str:
    """Generic table renderer for consistent style across commands.
    `columns` is a list of either str (column name) or (name, justify) tuples.
    `rows` is a list of tuples whose length matches `columns`.
    `border_style` overrides the wrapping panel border (default: dim)."""
    buf = StringIO()
    local = Console(file=buf, force_terminal=_stdout_is_tty(), width=_buffer_width())
    t = _make_inner_table()
    for col in columns:
        if isinstance(col, tuple):
            name, justify = col
            t.add_column(name, justify=justify, no_wrap=True, style=_column_style(name))
        else:
            t.add_column(col, no_wrap=True, style=_column_style(col))
    for r in rows:
        t.add_row(*[str(x) for x in r])
    local.print(_panel(t, title, border_style=border_style))
    return buf.getvalue()


def strip_markup(text: str) -> str:
    """Remove Rich markup tags from a string, for contexts that don't render Rich
    (e.g. questionary menus, typer prompts)."""
    return _RICH_MARKUP_RE.sub("", text)


def success(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def warning(msg: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {msg}")


def error(msg: str) -> None:
    console.print(f"[red]✗[/red] {msg}")


def info(msg: str) -> None:
    console.print(f"[blue]ⓘ[/blue] {msg}")


def select_apps_interactive(choices: list[tuple[str, str, bool]]) -> list[str]:
    """choices: list of (appid, label, exists).
    When exists=True the item is shown but disabled (already configured)."""
    qchoices = []
    for appid, label, exists in choices:
        if exists:
            qchoices.append(questionary.Choice(
                title=f"{label}  [already configured]",
                value=appid,
                disabled="already exists",
            ))
        else:
            qchoices.append(questionary.Choice(title=label, value=appid))
    return questionary.checkbox(
        "Which games to initialize? (Space to select, Enter to confirm)",
        choices=qchoices,
    ).ask() or []


def select_items_interactive(prompt: str, choices: list[tuple[str, str]]) -> list[str]:
    """Generic multi-select via questionary checkbox.
    `choices`: list of (label, value). Returns the selected values."""
    qchoices = [questionary.Choice(title=label, value=value) for label, value in choices]
    return questionary.checkbox(prompt, choices=qchoices).ask() or []


def select_one_interactive(prompt: str, choices: list[tuple[str, str]]) -> str | None:
    """Single-select via questionary radio. choices: list of (label, value).
    Returns the selected value, or None if cancelled."""
    qchoices = [questionary.Choice(title=label, value=value) for label, value in choices]
    return questionary.select(prompt, choices=qchoices).ask()
