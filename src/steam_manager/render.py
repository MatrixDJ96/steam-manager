"""Output formatting: rich tables, success/warning/error, questionary prompts."""
from __future__ import annotations

import re
import shutil
import sys
from io import StringIO
from typing import Iterable
from urllib.parse import quote

import questionary
from prompt_toolkit.keys import Keys
from rich import box
from rich.console import Console
from rich.markup import escape
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

# Help text (rich-click) reads best at a bounded measure, so it is capped even
# when the terminal is wider. Data tables are not — they size to content.
MAX_HELP_WIDTH = 120

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

    Sizes to its content (`expand=False`): the table grows just wide enough to
    fit its columns and stops, so it takes horizontal space only when the
    content needs it and never leaves columns truncated while space is free.
    Bounded by the Console width, so a narrow terminal still ellipsis-truncates.

    Per-row styling (bold/dim/...) is applied via `Table.add_row(..., style=...)`
    by callers when they have semantic info (e.g. `list` marks drift rows bold)."""
    return Table(
        show_header=True,
        header_style="bold dim",
        show_lines=False,
        box=None,
        padding=(0, 2),
        expand=False,
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
        expand=False,
    )


def effective_max_width() -> int:
    """Width ceiling for tables/panels — the full terminal width.

    Tables size to their content (see `_make_inner_table`), so this is only an
    upper bound: a table never grows past the terminal, and only that wide when
    its content needs it. No terminal (CliRunner, pipe): TABLE_WIDTH = 100.
    """
    cols = shutil.get_terminal_size(fallback=(0, 0)).columns
    if cols <= 0:
        return TABLE_WIDTH
    return cols


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


# Display order + labels for the games/applications grouping. A change with
# no "section" key (e.g. the restore preview, which diffs raw VDF and has no
# app-type info) sorts into a single unlabelled group, preserving the
# original layout. The label prefix only appears when both kinds are present.
SECTION_ORDER = ("games", "applications")
SECTION_LABELS = {"games": "Games", "applications": "Applications"}


def _diff_col_min(changes: list[dict]) -> dict[str, int]:
    """Max display width per column across all changes, so every diff sub-table
    shares the same min-widths and the panels line up across sections."""
    def disp(v) -> int:
        return len(str(v) if v is not None else "<none>")
    if not changes:
        return {"appid": 5, "name": 4, "from": 4, "to": 2}
    return {
        "appid": max(5, *(disp(c["appid"]) for c in changes)),
        "name":  max(4, *(disp(c["name"]) for c in changes)),
        "from":  max(4, *(disp(c["old"]) for c in changes)),
        "to":    max(2, *(disp(c["new"]) for c in changes)),
    }


def _diff_table(items: list[dict], col_min: dict[str, int]) -> Table:
    """A four-column From→To table for one group of changes."""
    t = _make_inner_table()
    t.add_column("AppID", justify="right", style="bold cyan", no_wrap=True,
                 min_width=col_min["appid"])
    t.add_column("Name", no_wrap=True, min_width=col_min["name"])
    t.add_column("From", style="red", no_wrap=True, min_width=col_min["from"])
    t.add_column("To", style="green", no_wrap=True, min_width=col_min["to"])
    for c in items:
        # escape(): the From/To values are user data (launch options, shortcut
        # names) — a bracketed value must render literally, not as markup.
        old = escape(str(c["old"])) if c["old"] is not None else "[dim]<none>[/dim]"
        new = escape(str(c["new"])) if c["new"] is not None else "[dim]<none>[/dim]"
        t.add_row(link_cell(c.get("compatdata_path", ""), c["appid"]),
                  link_cell(c.get("install_path", ""), c["name"]), old, new)
    return t


def _diff_field_panels(console: Console, section_changes: list[dict],
                       prefix: str | None, col_min: dict[str, int]) -> None:
    """Print one section's panels: Compat tool, Launch options per user, then
    Non-Steam shortcuts per user."""
    def titled(title: str) -> str:
        return f"{prefix} [dim]·[/dim] {title}" if prefix else title

    def _by_user(field: str) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for c in section_changes:
            if c["field"] == field:
                grouped.setdefault(c.get("user") or "-", []).append(c)
        return grouped

    def _user_title(base: str, user: str) -> str:
        return f"{base} [dim]—[/dim] [cyan]user[/cyan]:[bold cyan]{user}[/bold cyan]"

    compat = [c for c in section_changes if c["field"] == "compat_tool"]
    if compat:
        console.print(_panel(_diff_table(compat, col_min), titled("Compat tool"),
                             border_style=PANEL_BORDER_WARN))

    by_user = _by_user("launch_options")
    multi_user = len(by_user) > 1
    for user, items in by_user.items():
        title = _user_title("Launch options", user) if multi_user else "Launch options"
        console.print(_panel(_diff_table(items, col_min), titled(title),
                             border_style=PANEL_BORDER_WARN))

    for user, items in _by_user("shortcuts").items():
        console.print(_panel(_diff_table(items, col_min),
                             titled(_user_title("Non-Steam shortcuts", user)),
                             border_style=PANEL_BORDER_WARN))

    scb = [c for c in section_changes if c["field"] == "scb_conf"]
    if scb:
        console.print(_panel(_diff_table(scb, col_min),
                             titled("ScopeBuddy configs"),
                             border_style=PANEL_BORDER_WARN))


def diff_table_str(changes: list[dict]) -> str:
    """Renders diff output grouped by games/applications, then by field type and
    (for launch options) by user. Drift is a warning state, so the wrapping
    panels use a yellow border.

    All sub-tables share the same column widths (computed from all changes at once)
    so the columns line up visually across the multiple panels. The games/apps
    label is shown only when changes span both kinds; a single kind (or changes
    without a `section`, as from `restore`) renders without the prefix."""
    buf = StringIO()
    local = Console(file=buf, force_terminal=_stdout_is_tty(), width=_buffer_width())
    col_min = _diff_col_min(changes)

    by_section: dict[str | None, list[dict]] = {}
    for c in changes:
        by_section.setdefault(c.get("section"), []).append(c)
    ordered = ([k for k in SECTION_ORDER if k in by_section]
               + [k for k in by_section if k not in SECTION_ORDER])
    show_prefix = len(by_section) > 1
    for skey in ordered:
        prefix = SECTION_LABELS.get(skey) if show_prefix else None
        _diff_field_panels(local, by_section[skey], prefix, col_min)

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


def select_one_interactive(prompt: str, choices: list, default: str | None = None) -> str | None:
    """Single-select via questionary radio.

    Each element of `choices` is one of:
    - `(label, value)` — plain text choice
    - `None` — inserts a blank `questionary.Separator` (visual gap)
    - `questionary.Separator(line)` — passed through; use for titled
      group dividers like `Separator("── Custom ──")`
    - `questionary.Choice(...)` — passed through verbatim, useful for
      formatted titles (`title=[(style, text), ...]`) that render colours
      and dim/bold inside the picker.

    `default` pre-positions the cursor on the choice whose value matches. A
    `default` that matches no selectable choice is ignored (the picker just
    starts at the top) — questionary would otherwise raise, so a stale current
    value (e.g. a compat_tool no longer installed) must not crash the picker.

    Returns the selected value, or None if cancelled.
    """
    qchoices: list = []
    selectable: set = set()
    for item in choices:
        if item is None:
            qchoices.append(questionary.Separator())
        elif isinstance(item, questionary.Separator):
            qchoices.append(item)
        elif isinstance(item, questionary.Choice):
            qchoices.append(item)
            if not item.disabled:
                selectable.add(item.value)
        else:
            label, value = item
            qchoices.append(questionary.Choice(title=label, value=value))
            selectable.add(value)
    if default not in selectable:
        default = None
    return questionary.select(prompt, choices=qchoices, default=default).ask()


class _Back:
    """Sentinel result meaning the user backed out of a `menu()` — via the
    Back/Exit entry, the Esc key, or Ctrl-C. Callers test `result is BACK`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "BACK"


BACK = _Back()

# Shown after every menu title so the controls are always discoverable.
_MENU_INSTRUCTION = "↑↓ move · Enter select · Esc back"


def menu(
    title: str,
    options: list,
    *,
    default: str | None = None,
    back_label: str = "← Back",
    instruction: str = _MENU_INSTRUCTION,
) -> object:
    """Single-select menu with one uniform layout and reliable back-navigation.

    `options` entries are each a `(label, value)` pair, `None` (a blank
    separator), or a passed-through `questionary.Separator` / `questionary.Choice`.
    A `back_label` entry is appended automatically after a divider (use e.g.
    "Exit" for a top-level menu); the menu always offers a visible way out.

    Returns the selected value, or `BACK` when the user backs out — through the
    Back entry, the Esc key, or Ctrl-C — so every caller handles a single exit
    case. `default` pre-positions the cursor and is ignored if it matches no
    selectable entry (questionary would otherwise raise)."""
    qchoices: list = []
    selectable: set = set()
    for item in options:
        if item is None:
            qchoices.append(questionary.Separator())
        elif isinstance(item, questionary.Separator):
            qchoices.append(item)
        elif isinstance(item, questionary.Choice):
            qchoices.append(item)
            if not item.disabled:
                selectable.add(item.value)
        else:
            label, value = item
            qchoices.append(questionary.Choice(title=label, value=value))
            selectable.add(value)
    qchoices.append(questionary.Separator())
    qchoices.append(questionary.Choice(title=back_label, value=BACK))
    if default not in selectable:
        default = None

    question = questionary.select(
        title, choices=qchoices, default=default, instruction=instruction,
    )
    # questionary binds only Ctrl-C / Ctrl-Q; wire Esc to the same back result.
    # Non-eager so prompt_toolkit can still disambiguate arrow-key escape
    # sequences (which also start with Esc) before firing.
    question.application.key_bindings.add(Keys.Escape)(
        lambda event: event.app.exit(result=BACK)
    )
    answer = question.ask()  # None on Ctrl-C
    return BACK if answer is None else answer


_MULTISELECT_INSTRUCTION = "Space toggle · ↑↓ move · Enter confirm · Esc cancel"


def multiselect(
    title: str,
    options: list,
    *,
    instruction: str = _MULTISELECT_INSTRUCTION,
) -> object:
    """Multi-select checkbox with one concise layout and Esc-to-cancel.

    `options` entries are `(label, value)` pairs or passed-through
    `questionary.Choice` (use a Choice for `checked=` state or a styled title).
    Returns the list of selected values, or `BACK` when cancelled (Esc / Ctrl-C).
    An empty *confirmed* selection returns `[]` — distinct from a cancel — so a
    caller can tell "deselect everything" from "never mind"."""
    qchoices: list = []
    for item in options:
        if isinstance(item, (questionary.Choice, questionary.Separator)):
            qchoices.append(item)
        else:
            label, value = item
            qchoices.append(questionary.Choice(title=label, value=value))
    question = questionary.checkbox(title, choices=qchoices, instruction=instruction)
    question.application.key_bindings.add(Keys.Escape)(
        lambda event: event.app.exit(result=BACK)
    )
    answer = question.ask()  # None on Ctrl-C
    return BACK if answer is None else answer


def dim(text: str) -> tuple[str, str]:
    """A `(style, text)` fragment rendered dim — for the secondary part of a
    formatted picker title (e.g. an AppID after a game name)."""
    return ("fg:ansibrightblack", text)


def prompt_text(message: str, default: str = "") -> str | None:
    """Free-form text input via questionary. Returns None if cancelled (Ctrl-C)."""
    return questionary.text(message, default=default).ask()


def confirm(message: str, default: bool = True) -> bool:
    """Yes/No prompt via questionary. Returns `default` if cancelled (Ctrl-C),
    so callers can rely on the result being a bool without further guards."""
    result = questionary.confirm(message, default=default).ask()
    if result is None:
        return False
    return bool(result)


def prompt_int(message: str, default: int | None = None, minimum: int = 1) -> int | None:
    """Integer input with bounds validation. Returns None if cancelled."""
    def _validate(s: str) -> bool | str:
        s = s.strip()
        if not s:
            return "Required."
        try:
            v = int(s)
        except ValueError:
            return "Must be an integer."
        if v < minimum:
            return f"Must be ≥ {minimum}."
        return True

    default_str = str(default) if default is not None else ""
    result = questionary.text(message, default=default_str, validate=_validate).ask()
    if result is None:
        return None
    return int(result.strip())
