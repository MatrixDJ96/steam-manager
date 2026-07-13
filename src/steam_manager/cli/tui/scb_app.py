"""Textual dashboard for `steam-manager scopebuddy`.

The full-screen counterpart to `scopebuddy observe`: one screen listing every
installed game with its scopebuddy status and whether its per-game `.conf`
exists, plus a separate table of orphan configs. Enter (or a click) on a row
opens a per-row action modal; `i` bulk-creates every missing stub. Every
mutation (init a stub, delete an orphan) reloads the row model through the
pure `_scb_core.load_rows`, so the display always mirrors disk.

This module drives the pure `cli._scb_core` core and the modal screens in
`cli.tui.widgets`; it is imported lazily by the dispatcher so non-TUI
scopebuddy invocations never load Textual.
"""
from __future__ import annotations

import subprocess

from importlib.resources import files
from pathlib import Path

import typer

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Input, Static

from steam_manager.cli._checkpoint import make_checkpoint
from steam_manager.cli._editor import choose_editor
from steam_manager.cli._scb_core import ScbRow, load_rows
from steam_manager.cli.tui.widgets import ConfirmScreen, ScbRowScreen
from steam_manager.io.scopebuddy import delete_config, init_stub
from steam_manager.models import SteamApp


class _ScbTable(DataTable):
    """A dashboard table with its Enter binding surfaced in the footer: Enter
    (or a click) selects the row and the App opens the per-row action modal."""

    BINDINGS = [Binding("enter", "select_cursor", "Actions")]


class ScbApp(App):
    """One-screen dashboard for the per-game ScopeBuddy configs."""

    CSS = files("steam_manager.cli.tui").joinpath("app.tcss").read_text(encoding="utf-8")
    TITLE = "steam-manager · scopebuddy"

    BINDINGS = [
        Binding("slash", "filter", "Filter"),
        Binding("i", "init_missing", "Init missing"),
        Binding("r", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        scb_dir: Path,
        games: list[SteamApp],
        launch_options: dict[str, str | None],
    ) -> None:
        super().__init__()
        self._scb_dir = scb_dir
        self._games = games
        self._launch = launch_options
        self._rows: list[ScbRow] = []
        self._game_rows: list[ScbRow] = []      # game rows currently shown (post-filter)
        self._orphan_rows: list[ScbRow] = []    # orphan rows currently shown

    # ----- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        yield Input(placeholder="filter games…", id="filter")
        yield _ScbTable(id="games")
        yield _ScbTable(id="orphans")
        # No palette hint: at 80 columns it would push the last binding out of
        # the footer (Ctrl+P still opens the palette).
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        games = self.query_one("#games", DataTable)
        games.cursor_type = "row"
        games.add_columns("Name", "AppID", "ScopeBuddy", "Config")
        orphans = self.query_one("#orphans", DataTable)
        orphans.cursor_type = "row"
        orphans.add_columns("AppID", "Path")
        self._reload()
        games.focus()

    # ----- rendering --------------------------------------------------------

    def _reload(self) -> None:
        """Recompute the row model and repopulate every widget. Games and
        launch options stay fixed for the session; only the conf files on disk
        change, so a fresh `load_rows` is enough to reflect a mutation."""
        self._rows = load_rows(self._scb_dir, self._games, self._launch)
        self._render_summary()
        self._populate_games()
        self._populate_orphans()

    def _render_summary(self) -> None:
        active = sum(1 for r in self._rows if r.status == "active")
        missing = sum(1 for r in self._rows if r.status == "missing")
        orphans = sum(1 for r in self._rows if r.status == "orphan")
        self.query_one("#summary", Static).update(
            f"{active} active · {missing} missing · {orphans} orphans")

    def _populate_games(self) -> None:
        table = self.query_one("#games", DataTable)
        table.clear()
        flt = self.query_one("#filter", Input).value.strip().lower()
        self._game_rows = []
        for r in self._rows:
            if r.status == "orphan":
                continue
            if flt and flt not in r.name.lower() and flt not in r.appid:
                continue
            self._game_rows.append(r)
            scb = "yes" if r.status in ("active", "missing") else "-"
            conf = "present" if r.conf_path.exists() else "missing"
            # Name/AppID are user data → Text() so they are never cell markup.
            table.add_row(Text(r.name), Text(r.appid), scb, conf)

    def _populate_orphans(self) -> None:
        table = self.query_one("#orphans", DataTable)
        table.clear()
        self._orphan_rows = [r for r in self._rows if r.status == "orphan"]
        for r in self._orphan_rows:
            table.add_row(Text(r.appid), Text(str(r.conf_path)))
        # Hide the orphans table entirely when there is nothing to show.
        table.display = bool(self._orphan_rows)

    # ----- selection --------------------------------------------------------

    def _row_at(self, table_id: str, rows: list[ScbRow]) -> ScbRow | None:
        if not rows:
            return None
        idx = self.query_one(f"#{table_id}", DataTable).cursor_row
        if idx is None or not (0 <= idx < len(rows)):
            return None
        return rows[idx]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter or a click on either table opens that row's action modal."""
        if event.data_table.id == "games":
            self._open_row(self._row_at("games", self._game_rows))
        elif event.data_table.id == "orphans":
            self._open_row(self._row_at("orphans", self._orphan_rows))

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

    def action_reload(self) -> None:
        self._reload()
        self.notify("Reloaded.")

    @work
    async def action_init_missing(self) -> None:
        """`i`: confirm, then create an L1 stub for every `missing` row."""
        missing = [r for r in self._rows if r.status == "missing"]
        if not missing:
            self.notify("Nothing missing.")
            return
        if await self.push_screen_wait(
                ConfirmScreen(f"Create {len(missing)} missing stub(s)?")):
            for r in missing:
                init_stub(r.conf_path, r.name)
            self._reload()
            self.notify(f"Created {len(missing)} stub(s).")

    @work
    async def _open_row(self, row: ScbRow | None) -> None:
        """Per-row modal: init a missing stub, open the conf in $EDITOR, or
        delete an orphan (checkpointed). The modal only decides; the write
        happens here so a reload always follows."""
        if row is None:
            return
        conf_present = row.conf_path.exists()
        is_orphan = row.status == "orphan"
        choice = await self.push_screen_wait(
            ScbRowScreen(row.name, row.status, conf_present, is_orphan))
        if choice == "init":
            init_stub(row.conf_path, row.name)
            self._reload()
            self.notify(f"Created {row.conf_path.name}.")
        elif choice == "editor":
            self._open_editor(row.conf_path)
        elif choice == "delete":
            stem = row.conf_path.stem
            if await self.push_screen_wait(ConfirmScreen(
                    f"Delete {stem}.conf? A checkpoint is created first.")):
                make_checkpoint(trigger="scb-delete",
                                files={f"scopebuddy/{stem}.conf": row.conf_path})
                delete_config(row.conf_path)
                self._reload()
                self.notify(f"Deleted {stem}.conf.")

    def _open_editor(self, conf_path: Path) -> None:
        """Open one conf in the chosen editor, suspending the TUI while it runs.
        A headless driver cannot suspend, so the editor is invoked directly
        there; a missing editor becomes an error notification."""
        try:
            argv = choose_editor()
        except typer.BadParameter as exc:
            self.notify(str(exc), severity="error")
            return
        try:
            with self.suspend():
                subprocess.call(argv + [str(conf_path)])
        except SuspendNotSupported:
            subprocess.call(argv + [str(conf_path)])
        self._reload()
