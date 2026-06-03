"""Textual TUI for `steam-manager config`.

The only module in the package that imports Textual. It drives the pure
`_wizard_core` reducers: the whole policy is visible on one screen and edited
in place, queued edits show in a Pending pane, and a single **Save** writes
`policies.toml` (never Steam files — run `steam-manager apply` for that).
"""
from __future__ import annotations

from importlib.resources import files
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Static

from steam_manager.cli import _wizard_core as core
from steam_manager.cli.tui.widgets import (
    NONE,
    CompatPickerScreen,
    ConfirmScreen,
    LaunchPickerScreen,
    MaxBackupsScreen,
    TargetUsersScreen,
)


def _fmt(v: Any) -> str:
    """Display a value, with an em dash for empty."""
    if v is None or v == "":
        return "—"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) or "—"
    return str(v)


def _fmt_new(v: Any) -> str:
    return "(unset)" if v is core._UNSET else _fmt(v)


_FIELD_LABELS = {
    "compat_tool": "compat tool",
    "launch_options": "launch options",
    "ignore": "ignore",
}
_GLOBAL_LABELS = {
    "games.compat_tool": "Games · compat tool",
    "games.launch_options": "Games · launch options",
    "applications.compat_tool": "Applications · compat tool",
    "applications.launch_options": "Applications · launch options",
    "general.target_users": "Target users",
    "general.max_backups": "Max backups",
}


class ConfigApp(App):
    """One-screen editor for the user policy file."""

    CSS = files("steam_manager.cli.tui").joinpath("app.tcss").read_text(encoding="utf-8")
    TITLE = "steam-manager · config"

    BINDINGS = [
        ("c", "edit_compat", "Compat"),
        ("l", "edit_launch", "Launch"),
        ("space", "toggle_ignore", "Ignore"),
        ("g", "default('games', 'compat')", "Games compat"),
        ("G", "default('games', 'launch')", "Games launch"),
        ("p", "default('applications', 'compat')", "Apps compat"),
        ("P", "default('applications', 'launch')", "Apps launch"),
        ("u", "target_users", "Targets"),
        ("b", "max_backups", "Backups"),
        ("slash", "filter", "Filter"),
        ("s", "save", "Save"),
        ("d", "discard", "Discard"),
        ("r", "reset", "Reset"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, ctx=None, state: core.WizardState | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self.state = state if state is not None else core.load_state(ctx)
        self._visible: list[core.GameRow] = []
        self._appid_names: dict[str, str] = {}

    # ----- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="drift")
        with Horizontal(id="defaults"):
            yield Static(id="def-games-compat", classes="card")
            yield Static(id="def-games-launch", classes="card")
            yield Static(id="def-apps-compat", classes="card")
            yield Static(id="def-apps-launch", classes="card")
        with Horizontal(id="body"):
            with Vertical(id="games-pane"):
                yield Input(placeholder="filter games…", id="filter")
                yield Static(id="empty-note")
                yield DataTable(id="games")
            with VerticalScroll(id="settings"):
                yield Static(id="targets", classes="setting")
                yield Static(id="backups", classes="setting")
        yield Static(id="pending-title")
        yield DataTable(id="pending")
        yield Footer()

    def on_mount(self) -> None:
        games = self.query_one("#games", DataTable)
        games.cursor_type = "row"
        games.add_columns("Name", "AppID", "Compat", "Launch")
        pending = self.query_one("#pending", DataTable)
        pending.add_columns("Setting", "From", "To")
        self._appid_names = {g.appid: g.name for g in self.state.data.games}
        self._refresh()
        games.focus()
        self.run_worker(self._compute_drift, thread=True, exclusive=True, group="drift")

    # ----- rendering --------------------------------------------------------

    def _refresh(self) -> None:
        s = self.state
        self.query_one("#def-games-compat", Static).update(
            f"Games compat\n[b]{_fmt(s.effective('games.compat_tool'))}[/b]")
        self.query_one("#def-games-launch", Static).update(
            f"Games launch\n[b]{_fmt(s.effective('games.launch_options'))}[/b]")
        self.query_one("#def-apps-compat", Static).update(
            f"Apps compat\n[b]{_fmt(s.effective('applications.compat_tool'))}[/b]")
        self.query_one("#def-apps-launch", Static).update(
            f"Apps launch\n[b]{_fmt(s.effective('applications.launch_options'))}[/b]")
        self.query_one("#targets", Static).update(
            f"Target users\n[b]{_fmt(s.effective('general.target_users'))}[/b]")
        self.query_one("#backups", Static).update(
            f"Max backups\n[b]{_fmt(s.effective('general.max_backups'))}[/b]")
        note = self.query_one("#empty-note", Static)
        if not s.data.steam_found:
            note.update("No Steam install found — editing policy only.")
        elif not s.data.games:
            note.update("No installed games found.")
        else:
            note.update("")
        self._populate_games()
        self._populate_pending()

    def _populate_games(self) -> None:
        games = self.query_one("#games", DataTable)
        games.clear()
        flt = self.query_one("#filter", Input).value.strip().lower()
        ignored = core._effective_ignored(self.state)
        self._visible = []
        for g in self.state.data.games:
            if flt and flt not in g.name.lower() and flt not in g.appid:
                continue
            self._visible.append(g)
            marker = " ⊘" if g.appid in ignored else ""
            compat = self.state.effective(f"overrides.{g.appid}.compat_tool") or g.policy_compat
            launch = self.state.effective(f"overrides.{g.appid}.launch_options") or g.policy_launch
            games.add_row(f"{g.name}{marker}", g.appid, _fmt(compat), _fmt(launch))

    def _populate_pending(self) -> None:
        pending = self.query_one("#pending", DataTable)
        pending.clear()
        for c in self.state.pending:
            pending.add_row(self._pending_label(c), _fmt(c.old), _fmt_new(c.new))
        self.query_one("#pending-title", Static).update(
            f"Pending ({self.state.pending_count})")

    def _pending_label(self, change: core.Change) -> str:
        key = change.key
        if key.startswith("overrides."):
            appid, _, field = key[len("overrides."):].partition(".")
            name = self._appid_names.get(appid, appid)
            return f"{name} · {_FIELD_LABELS.get(field, field)}"
        return _GLOBAL_LABELS.get(key, key)

    def _selected_game(self) -> core.GameRow | None:
        if not self._visible:
            return None
        idx = self.query_one("#games", DataTable).cursor_row
        if idx is None or not (0 <= idx < len(self._visible)):
            return None
        return self._visible[idx]

    def _reload(self) -> None:
        self.state = core.load_state(self._ctx)
        self._appid_names = {g.appid: g.name for g in self.state.data.games}
        self._refresh()

    # ----- drift (UI-layer, async; never blocks the editor) -----------------

    def _compute_drift(self) -> None:
        try:
            from steam_manager import policy
            from steam_manager.cli import _drift
            from steam_manager.cli._common import policy_paths, steam_root
            from steam_manager.io import discovery

            ctx = self._ctx or discovery.discover(steam_root=steam_root())
            apps = discovery.list_apps(ctx)
            users = discovery.list_users(ctx)
            engine = policy.load(policy_paths())
            changes = _drift.compute_drift(ctx, apps, users, engine)
            n = len({c["appid"] for c in changes})
            msg = (f"⚠ {n} game(s) would change on disk — run `steam-manager apply`"
                   if n else "✓ in sync with disk")
        except Exception:  # noqa: BLE001 — drift is decorative, never fatal
            msg = "drift unavailable"
        self.call_from_thread(self._set_drift, msg)

    def _set_drift(self, msg: str) -> None:
        self.query_one("#drift", Static).update(msg)

    # ----- input events -----------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._populate_games()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.query_one("#games", DataTable).focus()

    # ----- actions ----------------------------------------------------------

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_toggle_ignore(self) -> None:
        row = self._selected_game()
        if row is not None:
            self.state = core.toggle_ignore(self.state, row.appid)
            self._refresh()

    @work
    async def action_edit_compat(self) -> None:
        row = self._selected_game()
        if row is None:
            return
        result = await self.push_screen_wait(
            CompatPickerScreen(self.state.data.tools, f"Compat tool · {row.name}"))
        if result is None:
            return
        value = None if result == NONE else result
        self.state = core.set_compat_tool(self.state, f"overrides.{row.appid}", value)
        self._refresh()

    @work
    async def action_edit_launch(self) -> None:
        row = self._selected_game()
        if row is None:
            return
        await self._edit_launch_scope(f"overrides.{row.appid}")

    @work
    async def action_default(self, section: str, field: str) -> None:
        if field == "compat":
            result = await self.push_screen_wait(
                CompatPickerScreen(self.state.data.tools, f"{section} · compat tool"))
            if result is None:
                return
            value = None if result == NONE else result
            self.state = core.set_compat_tool(self.state, section, value)
            self._refresh()
        else:
            await self._edit_launch_scope(section)

    async def _edit_launch_scope(self, scope: str) -> None:
        current = self.state.effective(f"{scope}.launch_options")
        result = await self.push_screen_wait(
            LaunchPickerScreen(current if isinstance(current, str) else ""))
        if result is None:
            return
        value = None if result == NONE else result
        self.state = core.set_launch_options(self.state, scope, value)
        self._refresh()

    @work
    async def action_max_backups(self) -> None:
        result = await self.push_screen_wait(
            MaxBackupsScreen(self.state.effective("general.max_backups")))
        if result is None:
            return
        self.state = core.set_max_backups(self.state, result)
        self._refresh()

    @work
    async def action_target_users(self) -> None:
        if not self.state.data.users:
            self.notify("No Steam accounts found.")
            return
        current = self.state.effective("general.target_users") or []
        result = await self.push_screen_wait(
            TargetUsersScreen(self.state.data.users, current))
        if result is None:
            return
        self.state = core.set_target_users(self.state, list(result))
        self._refresh()

    async def action_save(self) -> None:
        if not self.state.pending:
            self.notify("Nothing to save.")
            return
        n = core.apply(self.state)
        self._reload()
        self.notify(f"Saved policy ({n} change(s)). Run `steam-manager apply` to write Steam.")

    @work
    async def action_discard(self) -> None:
        if not self.state.pending:
            return
        if await self.push_screen_wait(
                ConfirmScreen(f"Discard {self.state.pending_count} change(s)?")):
            self.state = core.discard(self.state)
            self._refresh()

    @work
    async def action_reset(self) -> None:
        if not core.can_reset():
            self.notify("Already at factory defaults.")
            return
        if await self.push_screen_wait(
                ConfirmScreen("Delete the user policy and revert to factory defaults?")):
            core.reset()
            self._reload()
            self.notify("Reset to factory defaults.")

    @work
    async def action_quit(self) -> None:
        if self.state.pending and not await self.push_screen_wait(
                ConfirmScreen(f"Discard {self.state.pending_count} unsaved change(s) and quit?")):
            return
        self.exit()
