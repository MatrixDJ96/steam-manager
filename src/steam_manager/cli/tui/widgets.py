"""Modal screens for the config TUI: the per-game editor and settings hubs,
compat / launch / target-users / max-backups pickers, and a yes-no confirm.
Each dismisses with a plain value the App feeds to a `_wizard_core` reducer —
the widgets never build a Change or touch the disk.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, SelectionList, Static
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

# Sentinels returned through `dismiss`.
NONE = "__none__"   # clear the key (Steam default / empty)

_LAUNCH_TEMPLATES = (
    "scopebuddy -- %command%",
    "mangohud %command%",
    "gamemoderun %command%",
)


def _highlight_first_enabled(ol: OptionList) -> None:
    """Highlight the first selectable option, so Enter works the moment the
    picker opens (options added after mount start with no highlight)."""
    for i in range(ol.option_count):
        if not ol.get_option_at_index(i).disabled:
            ol.highlighted = i
            return


class _PickOneModal(ModalScreen):
    """Title + OptionList + hint modal that dismisses with the selected
    option's id, or None on cancel (Esc). Subclasses supply the title and the
    option rows; user data in either goes through `markup=False` / `Content()`
    so it is never parsed as markup ("[PROTOTYPE]" is a real title)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, options: list[Option], list_id: str) -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._list_id = list_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static(self._title, markup=False, classes="modal-title")
            yield OptionList(*self._options, id=self._list_id)
            yield Static("Enter to choose · Esc to cancel", classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class GameEditScreen(_PickOneModal):
    """Single entry point for editing one game: shows its current compat tool,
    launch options, and ignore flag. Dismisses with `'compat'`, `'launch'`, or
    `'ignore'` (the App routes to the matching picker/reducer), or None on
    cancel (Esc)."""

    def __init__(self, name: str, compat: str, launch: str, ignored: bool) -> None:
        super().__init__(name, [
            Option(Content(f"Compat tool      {compat}"), id="compat"),
            Option(Content(f"Launch options   {launch}"), id="launch"),
            Option("Un-ignore this game" if ignored else "Ignore this game",
                   id="ignore"),
        ], list_id="game-actions")


class SettingsScreen(_PickOneModal):
    """Hub for the global defaults and settings. Takes `(key, label, value)`
    rows and dismisses with the picked dotted key (the App routes to the
    matching picker), or None on cancel (Esc)."""

    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        super().__init__("Defaults & settings", [
            Option(Content(f"{label:<28} {value}"), id=key)
            for key, label, value in rows
        ], list_id="settings-options")


class CompatPickerScreen(ModalScreen):
    """Pick a compat tool. Dismisses with a tech_name, `NONE` to clear, or None
    on cancel (Esc)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, tools, title: str = "Select a compat tool") -> None:
        super().__init__()
        self._tools = list(tools)
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static(self._title, markup=False, classes="modal-title")
            yield OptionList(id="options")
            yield Static("Enter to choose · Esc to cancel", classes="modal-hint")

    def on_mount(self) -> None:
        ol = self.query_one("#options", OptionList)
        if not self._tools:
            ol.add_option(Option("No compat tools found in compatibilitytools.d/.",
                                 disabled=True))
        custom = [t for t in self._tools if t.source == "custom"]
        official = [t for t in self._tools if t.source != "custom"]
        if custom:
            ol.add_option(Option("── Custom ──", disabled=True))
            for t in custom:
                ol.add_option(Option(Content(t.display_name), id=f"tool:{t.tech_name}"))
        if official:
            ol.add_option(Option("── Official ──", disabled=True))
            for t in official:
                ol.add_option(Option(Content(t.display_name), id=f"tool:{t.tech_name}"))
        ol.add_option(Option("── Special ──", disabled=True))
        ol.add_option(Option("None (Steam default)", id="none"))
        _highlight_first_enabled(ol)
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id or ""
        if oid == "none":
            self.dismiss(NONE)
        elif oid.startswith("tool:"):
            self.dismiss(oid[len("tool:"):])

    def action_cancel(self) -> None:
        self.dismiss(None)


class LaunchPickerScreen(ModalScreen):
    """Edit launch options. Dismisses with the string, `NONE` to clear, or None
    on cancel. Selecting a template fills the input; Enter on the input applies."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str = "") -> None:
        super().__init__()
        self._current = current or ""

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static("Launch options", markup=False, classes="modal-title")
            yield OptionList(id="templates")
            yield Input(value=self._current, placeholder="e.g. mangohud %command%",
                        id="launch-input")
            yield Static("Pick a template or type · Enter to apply · Esc to cancel",
                         classes="modal-hint")

    def on_mount(self) -> None:
        ol = self.query_one("#templates", OptionList)
        for t in _LAUNCH_TEMPLATES:
            ol.add_option(Option(t, id=f"tpl:{t}"))
        ol.add_option(Option("Clear (Steam default)", id="none"))
        _highlight_first_enabled(ol)
        self.query_one("#launch-input", Input).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id or ""
        if oid == "none":
            self.dismiss(NONE)
        elif oid.startswith("tpl:"):
            self.query_one("#launch-input", Input).value = oid[len("tpl:"):]
            self.query_one("#launch-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MaxBackupsScreen(ModalScreen):
    """Numeric input for max_backups. Dismisses with the raw string (the core
    validates) or None on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current) -> None:
        super().__init__()
        self._current = "" if current is None else str(current)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static("Max backups (≥ 1)", markup=False, classes="modal-title")
            yield Input(value=self._current, id="backups-input")
            yield Static("Enter to apply · Esc to cancel", classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one("#backups-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TargetUsersScreen(ModalScreen):
    """Pick target accounts. Dismisses with a spec list (`['active']`, `['*']`,
    or explicit account names) or None on cancel. Enter on a mode applies it;
    the third mode (or 'a') applies the checked specific accounts."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("a", "apply_specific", "Apply specific"),
    ]

    def __init__(self, users, current) -> None:
        super().__init__()
        self._users = list(users)
        self._current = set(str(x) for x in (current or []))

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static("Target accounts", markup=False, classes="modal-title")
            yield OptionList(
                Option("Active account (whoever is logged in)", id="active"),
                Option("All local accounts", id="all"),
                Option("The accounts checked below", id="specific"),
                id="modes",
            )
            names = self._current - {"active", "*"}
            yield SelectionList(
                *[Selection(u.account_name, u.account_name, u.account_name in names)
                  for u in self._users],
                id="accounts",
            )
            yield Static("Enter picks a mode · Space toggles accounts · Esc cancels",
                         classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one("#modes", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id or ""
        if oid == "active":
            self.dismiss(["active"])
        elif oid == "all":
            self.dismiss(["*"])
        elif oid == "specific":
            self.action_apply_specific()

    def action_apply_specific(self) -> None:
        selected = list(self.query_one("#accounts", SelectionList).selected)
        if selected:
            self.dismiss(selected)
        else:
            self.notify("Check at least one account first (Space toggles).",
                        severity="warning")

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen):
    """Yes/No confirm with clickable buttons ("No" pre-focused). Dismisses
    with a bool."""

    BINDINGS = [
        ("y", "yes", "Yes"),
        ("n", "no", "No"),
        ("escape", "no", "No"),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Static(self._question, markup=False, classes="modal-title")
            with Horizontal(classes="modal-buttons"):
                yield Button("Yes", variant="primary", id="yes")
                yield Button("No", id="no")
            yield Static("y = yes · n / Esc = no", classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
