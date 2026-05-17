"""Interactive wizard for `steam-manager config wizard`.

Design principles:

- **Flat, granular main menu.** Every entry takes the user *directly* to
  the picker that matters. No "What to edit? → Apply to? → Compat tool?"
  cascade — instead "Change Proton (default for all games)" is one click
  to the tool picker. Fewer prompts stacked on screen at any time.
- **Show-on-demand.** The current-configuration table is not printed
  automatically on every iteration; it's reachable via a dedicated
  "Show current configuration" menu entry. The default screen is just
  the menu.
- **Grouped picker.** The compat-tool picker uses `Separator` titles to
  visually group entries by source (Custom / Official / Special), so the
  list reads as three short groups instead of one long undifferentiated
  list. The launch-options picker groups Templates / Special the same way.
- **Breadcrumb header.** Before each value picker, a two-line header
  states what's being edited and the current value. The user always
  knows what context the picker belongs to without having to scroll back.
- **Decision separated from side-effect.** Sub-flows are pure functions
  that return `list[Change]`; `_apply_changes` is the single point that
  touches the filesystem. Wizard tests assert on the returned `Change`
  objects directly, without mocking `save_doc`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from io import StringIO
from typing import Any, Callable

import questionary
import tomlkit
import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from steam_manager import policy, render
from steam_manager.cli import _appinfo
from steam_manager.cli._appinfo import is_listable
from steam_manager.cli._common import policy_paths, steam_root
from steam_manager.io import compat_tools, discovery, policies_toml
from steam_manager.models import SteamContext


_UNSET = object()


@dataclass(frozen=True)
class Change:
    """A single pending modification to the user policy file."""
    key: str
    old: Any
    new: Any


# ----- entry point ----------------------------------------------------------


def run() -> None:
    try:
        ctx = discovery.discover(steam_root=steam_root())
    except FileNotFoundError as exc:
        render.error(str(exc))
        return

    while True:
        area = _pick_area()
        if area is None or area == "exit":
            return

        if area == "show":
            _print_current_config()
            continue
        if area == "reset":
            _flow_reset()
            continue

        flow = _AREA_FLOWS[area]
        try:
            changes = flow(ctx)
        except KeyboardInterrupt:
            render.warning("Cancelled.")
            continue

        changes = [c for c in changes if not _is_noop(c)]
        if not changes:
            continue

        _print_pending_changes(changes)
        if not render.confirm("Apply changes?", default=True):
            render.info("Discarded.")
            continue

        _apply_changes(changes)
        render.success(f"Applied {len(changes)} change(s).")


# ----- main menu ------------------------------------------------------------


def _pick_area() -> str | None:
    return render.select_one_interactive("What do you want to do?", [
        ("Change Proton (default for all games)", "compat-games"),
        ("Change Proton (for one game)", "compat-single"),
        ("Change launch options (default for all games)", "launch-games"),
        ("Change launch options (for one game)", "launch-single"),
        None,
        ("Toggle ignore list", "ignore-list"),
        None,
        ("Set target users", "target-users"),
        ("Set max backups", "max-backups"),
        None,
        ("Show current configuration", "show"),
        ("Reset to defaults", "reset"),
        None,
        ("Exit", "exit"),
    ])


# ----- breadcrumb header ---------------------------------------------------


def _print_breadcrumb(setting: str, scope: str, current: Any) -> None:
    """Two-line context header rendered before a value picker."""
    typer.echo()
    typer.secho(f"Editing: {setting} — [{scope}]", fg="cyan", bold=True)
    typer.secho(f"Current: {_format_value(current)}", fg="bright_black")
    typer.echo()


# ----- sub-flows: compat tool ----------------------------------------------


def _flow_compat_games(ctx: SteamContext) -> list[Change]:
    return _edit_compat_tool(ctx, "games")


def _flow_compat_single(ctx: SteamContext) -> list[Change]:
    appid = _pick_installed_game(ctx)
    if appid is None:
        return []
    return _edit_compat_tool(ctx, f"overrides.{appid}")


def _edit_compat_tool(ctx: SteamContext, scope: str) -> list[Change]:
    current = _effective(f"{scope}.compat_tool")
    tools = compat_tools.list_compat_tools(ctx)
    if not tools:
        render.warning("No compat tools found in compatibilitytools.d/ or via Proton appmanifest.")
        return []
    _print_breadcrumb("compat tool", scope, current)

    custom = [t for t in tools if t.source == "custom"]
    official = [t for t in tools if t.source == "official"]

    choices: list = []
    if custom:
        choices.append(questionary.Separator("── Custom ──"))
        for t in custom:
            choices.append(questionary.Choice(title=t.display_name, value=t.tech_name))
    if official:
        choices.append(questionary.Separator("── Official ──"))
        for t in official:
            choices.append(questionary.Choice(title=t.display_name, value=t.tech_name))
    choices.append(questionary.Separator("── Special ──"))
    choices.append(questionary.Choice(title="None (use Steam default)", value="__none__"))
    choices.append(questionary.Choice(title="Skip (keep current)", value="__keep__"))

    pick = render.select_one_interactive("Select:", choices, default=current)
    if pick is None or pick == "__keep__":
        return []
    new = _UNSET if pick == "__none__" else pick
    return [Change(f"{scope}.compat_tool", current, new)]


# ----- sub-flows: launch options -------------------------------------------


_LAUNCH_TEMPLATES: list[tuple[str, str]] = [
    ("scopebuddy -- %command%", "scopebuddy -- %command%"),
    ("mangohud %command%", "mangohud %command%"),
    ("gamemoderun %command%", "gamemoderun %command%"),
]


def _flow_launch_games(ctx: SteamContext) -> list[Change]:
    return _edit_launch_options("games")


def _flow_launch_single(ctx: SteamContext) -> list[Change]:
    appid = _pick_installed_game(ctx)
    if appid is None:
        return []
    return _edit_launch_options(f"overrides.{appid}")


def _edit_launch_options(scope: str) -> list[Change]:
    current = _effective(f"{scope}.launch_options")
    _print_breadcrumb("launch options", scope, current)

    choices: list = [questionary.Separator("── Templates ──")]
    for label, value in _LAUNCH_TEMPLATES:
        choices.append(questionary.Choice(title=label, value=value))
    choices.append(questionary.Separator("── Special ──"))
    choices.append(questionary.Choice(title="Custom…", value="__custom__"))
    choices.append(questionary.Choice(title="None (clear launch options)", value="__none__"))
    choices.append(questionary.Choice(title="Skip (keep current)", value="__keep__"))

    pick = render.select_one_interactive("Select:", choices, default=current)
    if pick is None or pick == "__keep__":
        return []
    if pick == "__none__":
        return [Change(f"{scope}.launch_options", current, _UNSET)]
    if pick == "__custom__":
        typed = render.prompt_text("Launch options:", default=str(current or ""))
        if typed is None:
            return []
        stripped = typed.strip()
        new = stripped if stripped else _UNSET
        return [Change(f"{scope}.launch_options", current, new)]
    return [Change(f"{scope}.launch_options", current, pick)]


# ----- sub-flows: target_users + max_backups --------------------------------


def _flow_target_users(ctx: SteamContext) -> list[Change]:
    users = discovery.list_users(ctx)
    if not users:
        render.error("No Steam accounts found.")
        return []
    current = _effective("general.target_users") or []
    current_list = list(current) if isinstance(current, list) else []
    current_set = set(current_list)

    _print_breadcrumb("target users", "general", current_list)

    qchoices: list = [
        questionary.Choice(
            "active (currently logged in)",
            value="active", checked="active" in current_set,
        ),
        questionary.Choice(
            "* (all local accounts)",
            value="*", checked="*" in current_set,
        ),
        questionary.Separator(),
    ]
    for u in users:
        suffix = "  (active)" if u.is_active else ""
        qchoices.append(questionary.Choice(
            f"{u.account_name}{suffix}",
            value=u.account_name, checked=u.account_name in current_set,
        ))
    selected = questionary.checkbox("Select:", choices=qchoices).ask()
    if selected is None:
        return []
    if not selected:
        render.warning("Empty selection — keeping current target_users.")
        return []
    if "*" in selected:
        selected = ["*"]
    arr = tomlkit.array()
    for v in selected:
        arr.append(v)
    return [Change("general.target_users", current_list, arr)]


def _flow_max_backups(ctx: SteamContext) -> list[Change]:
    raw = _effective("general.max_backups")
    try:
        current = int(raw) if raw is not None else 10
    except (ValueError, TypeError):
        current = 10
    _print_breadcrumb("max backups", "general", current)
    value = render.prompt_int("New value:", default=current, minimum=1)
    if value is None:
        return []
    return [Change("general.max_backups", current, value)]


# ----- sub-flow: ignore list (toggle) --------------------------------------


def _flow_ignore_list(ctx: SteamContext) -> list[Change]:
    games = _installed_games(ctx)
    if not games:
        render.warning("No installed games found.")
        return []
    current = _read_ignored_from_user_doc()
    _print_breadcrumb("ignore list", "overrides", f"{len(current)} game(s) ignored")
    qchoices = [
        questionary.Choice(
            f"{a.name} ({a.appid})",
            value=a.appid, checked=a.appid in current,
        )
        for a in games
    ]
    selected = questionary.checkbox("Games to ignore:", choices=qchoices).ask()
    if selected is None:
        return []
    selected_set = set(selected)
    changes: list[Change] = []
    for appid in sorted(selected_set - current):
        changes.append(Change(f"overrides.{appid}.ignore", None, True))
    for appid in sorted(current - selected_set):
        changes.append(Change(f"overrides.{appid}.ignore", True, _UNSET))
    return changes


# ----- sub-flow: reset (own confirm, no Change list) -----------------------


def _flow_reset() -> None:
    p = policies_toml.user_path()
    if not p.exists():
        render.info("Already at factory defaults (no user policy file).")
        return
    if not render.confirm(
        f"Discard {p} and revert to factory defaults?",
        default=False,
    ):
        render.info("Reset cancelled.")
        return
    p.unlink()
    render.success(f"Reset {p}.")


# ----- shared helpers -------------------------------------------------------


def _pick_installed_game(ctx: SteamContext) -> str | None:
    games = _installed_games(ctx)
    if not games:
        render.warning("No installed games found.")
        return None
    return render.select_one_interactive(
        "Which game?",
        [(f"{a.name} ({a.appid})", a.appid) for a in games],
    )


def _installed_games(ctx: SteamContext) -> list:
    types = _appinfo.appinfo_types()
    return sorted(
        (a for a in discovery.list_apps(ctx) if a.installed and is_listable(a, types)),
        key=lambda a: a.name.lower(),
    )


def _effective(key: str) -> Any:
    engine = policy.load(policy_paths())
    doc = policies_toml.render_effective_doc(engine)
    return policies_toml.get_dotted(doc, key)


def _apply_changes(changes: list[Change]) -> None:
    doc = policies_toml.load_doc()
    for c in changes:
        if c.new is _UNSET:
            policies_toml.unset_dotted(doc, c.key)
        else:
            policies_toml.set_dotted(doc, c.key, c.new)
    policies_toml.save_doc(doc)


def _is_noop(c: Change) -> bool:
    if c.new is _UNSET:
        return c.old is None
    if isinstance(c.new, list) and isinstance(c.old, list):
        return list(c.new) == list(c.old)
    return c.new == c.old


def _format_value(v: Any) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, list):
        return repr(list(v))
    return str(v)


def _format_new(c: Change) -> str:
    return "(unset)" if c.new is _UNSET else _format_value(c.new)


def _appids_with_ignore(overrides: Any) -> set[str]:
    if not isinstance(overrides, (dict, tomlkit.items.Table)):
        return set()
    return {
        appid for appid, section in overrides.items()
        if isinstance(section, (dict, tomlkit.items.Table))
        and section.get("ignore") is True
    }


def _read_ignored_from_user_doc() -> set[str]:
    return _appids_with_ignore(policies_toml.load_doc().get("overrides") or {})


# ----- print helpers (manual, no auto-render at loop top) ------------------


def _print_current_config() -> None:
    engine = policy.load(policy_paths())
    doc = policies_toml.render_effective_doc(engine)
    table = Table(
        show_header=False, box=box.HORIZONTALS, show_edge=False,
        padding=(0, 2), expand=True,
    )
    table.add_column("Setting", style="bold dim", no_wrap=True)
    table.add_column("Value")

    table.add_row("Target users",
                  _format_value(policies_toml.get_dotted(doc, "general.target_users")))
    table.add_row("Max backups",
                  _format_value(policies_toml.get_dotted(doc, "general.max_backups")))
    table.add_section()

    table.add_row("[bold]Games[/bold]", "")
    table.add_row("  Compat tool",
                  _format_value(policies_toml.get_dotted(doc, "games.compat_tool")))
    table.add_row("  Launch options",
                  _format_value(policies_toml.get_dotted(doc, "games.launch_options")))
    table.add_section()

    table.add_row("[bold]Applications[/bold]", "")
    table.add_row("  Compat tool",
                  _format_value(policies_toml.get_dotted(doc, "applications.compat_tool")))
    table.add_row("  Launch options",
                  _format_value(policies_toml.get_dotted(doc, "applications.launch_options")))

    overrides = policies_toml.get_dotted(doc, "overrides") or {}
    ignored = sorted(_appids_with_ignore(overrides))
    custom_count = sum(
        1 for _, section in overrides.items()
        if isinstance(section, (dict, tomlkit.items.Table))
        and any(k != "ignore" for k in section)
    )
    if ignored or custom_count:
        table.add_section()
        if ignored:
            table.add_row("Ignored games", ", ".join(ignored))
        if custom_count:
            table.add_row("Custom per-AppID", str(custom_count))

    buf = StringIO()
    is_tty = getattr(sys.stdout, "isatty", lambda: False)()
    local = Console(file=buf, force_terminal=is_tty, width=render.effective_max_width())
    local.print(Panel(
        table,
        title="[bold]Current configuration[/bold]",
        title_align="left",
        border_style=render.PANEL_BORDER_STYLE,
        padding=(0, 1),
    ))
    typer.echo(buf.getvalue())


def _print_pending_changes(changes: list[Change]) -> None:
    rows = [(c.key, _format_value(c.old), _format_new(c)) for c in changes]
    typer.echo(render.simple_table_str(
        "Pending changes",
        ["Key", "From", "To"],
        rows,
        border_style="yellow",
    ))


# ----- registry -------------------------------------------------------------


_AREA_FLOWS: dict[str, Callable[[SteamContext], list[Change]]] = {
    "compat-games": _flow_compat_games,
    "compat-single": _flow_compat_single,
    "launch-games": _flow_launch_games,
    "launch-single": _flow_launch_single,
    "target-users": _flow_target_users,
    "max-backups": _flow_max_backups,
    "ignore-list": _flow_ignore_list,
}
