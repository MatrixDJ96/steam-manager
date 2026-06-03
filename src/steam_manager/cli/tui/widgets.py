"""Modal screens for the config TUI: compat / launch / target-users / max-backups
pickers and a yes-no confirm. Each dismisses with a plain value the App feeds to
a `_wizard_core` reducer — the widgets never build a Change or touch the disk.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, SelectionList, Static
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

# Sentinels returned through `dismiss`.
NONE = "__none__"   # clear the key (Steam default / empty)

_LAUNCH_TEMPLATES = (
    "scopebuddy -- %command%",
    "mangohud %command%",
    "gamemoderun %command%",
)


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
            yield Static(self._title, classes="modal-title")
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
                ol.add_option(Option(t.display_name, id=f"tool:{t.tech_name}"))
        if official:
            ol.add_option(Option("── Official ──", disabled=True))
            for t in official:
                ol.add_option(Option(t.display_name, id=f"tool:{t.tech_name}"))
        ol.add_option(Option("── Special ──", disabled=True))
        ol.add_option(Option("None (Steam default)", id="none"))
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
            yield Static("Launch options", classes="modal-title")
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
            yield Static("Max backups (≥ 1)", classes="modal-title")
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
    'a' applies the checked specific accounts."""

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
            yield Static("Target accounts", classes="modal-title")
            yield OptionList(
                Option("Active account (whoever is logged in)", id="active"),
                Option("All local accounts", id="all"),
                id="modes",
            )
            names = self._current - {"active", "*"}
            yield SelectionList(
                *[Selection(u.account_name, u.account_name, u.account_name in names)
                  for u in self._users],
                id="accounts",
            )
            yield Static("Enter a mode · Space toggles accounts · 'a' applies them · Esc cancels",
                         classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one("#modes", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id or ""
        if oid == "active":
            self.dismiss(["active"])
        elif oid == "all":
            self.dismiss(["*"])

    def action_apply_specific(self) -> None:
        selected = list(self.query_one("#accounts", SelectionList).selected)
        if selected:
            self.dismiss(selected)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen):
    """Yes/No confirm. Dismisses with a bool."""

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
            yield Static(self._question, classes="modal-title")
            yield Static("y = yes · n / Esc = no", classes="modal-hint")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
