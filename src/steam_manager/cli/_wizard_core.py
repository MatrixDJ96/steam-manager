"""Pure, front-end-agnostic core for the config wizard / TUI.

Holds the decision/state seam shared by the classic questionary wizard
(`_wizard.py`) and the Textual TUI (`tui/`): the `Change` model, the
`_merge_pending`/`_is_noop` fold, the single `_apply_changes` write point,
and the single merged `_effective` read.

Imports only `policy`, `io`, and UI-free `cli` siblings — no questionary,
Rich, Typer, or Textual — so the edit logic stays unit-testable without a
terminal and without filesystem mocking beyond the load/apply boundary.
Drift is render-coupled (`_drift` -> `_targets` -> `render` -> questionary),
so it is deliberately NOT computed here; it lives in the UI layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import tomlkit

from steam_manager import policy
from steam_manager.cli import _appinfo
from steam_manager.cli._appinfo import is_listable
from steam_manager.cli._common import policy_paths, steam_root
from steam_manager.io import compat_tools, discovery, policies_toml
from steam_manager.models import CompatTool, SteamContext, SteamUser


_UNSET = object()


@dataclass(frozen=True)
class Change:
    """A single pending modification to the user policy file."""
    key: str
    old: Any
    new: Any


def _toml_array(values: list[str]):
    """Build a tomlkit array from a list of strings (preserves TOML formatting)."""
    arr = tomlkit.array()
    for v in values:
        arr.append(v)
    return arr


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


def _merge_pending(pending: list[Change], new_changes: list[Change]) -> list[Change]:
    """Fold new edits into the pending list, keyed by `Change.key`.

    A later edit of a key supersedes the earlier one (keeping its position);
    an edit that returns a key to its on-disk value (a no-op) drops it from
    pending — so re-picking the current value cleanly cancels a queued edit."""
    by_key: dict[str, Change] = {c.key: c for c in pending}
    for c in new_changes:
        if _is_noop(c):
            by_key.pop(c.key, None)
        else:
            by_key[c.key] = c
    return list(by_key.values())


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


def _installed_games(ctx: SteamContext) -> list:
    types = _appinfo.appinfo_types()
    return sorted(
        (a for a in discovery.list_apps(ctx) if a.installed and is_listable(a, types)),
        key=lambda a: a.name.lower(),
    )


# ----- state model ----------------------------------------------------------


@dataclass(frozen=True)
class GameRow:
    """One installed, listable game with its policy-resolved intent.

    `policy_compat`/`policy_launch` are the *resolved* policy values (section
    default + per-AppID override merged via `policy.resolve`) — what `apply`
    would write. `ignored` reflects an active `overrides.<appid>.ignore`.
    """
    appid: str
    name: str
    app_type: str | None
    policy_compat: str | None
    policy_launch: str | None
    ignored: bool


@dataclass
class WizardData:
    """Immutable snapshot of everything loaded once at `load_state`.

    `doc` is the rendered effective (factory+user) policy document; it backs
    `WizardState.effective` so per-key reads need no further disk access.
    `ignored_appids` is read from the USER doc only (matching the classic
    flow), so toggling ignore diffs against the user's own overrides.
    """
    games: tuple[GameRow, ...]
    users: tuple[SteamUser, ...]
    tools: tuple[CompatTool, ...]
    games_compat: str | None
    games_launch: str | None
    apps_compat: str | None
    apps_launch: str | None
    target_users: tuple[str, ...]
    max_backups: int
    ignored_appids: frozenset[str]
    steam_found: bool = True
    doc: Any = field(compare=False, repr=False, default=None)


@dataclass
class WizardState:
    """Loaded data plus the queued, not-yet-written edits.

    Reducers return a new `WizardState` (same `data`, new `pending`); the
    single `apply` boundary is the only thing that touches the filesystem.
    """
    data: WizardData
    pending: tuple[Change, ...] = ()

    @property
    def pending_count(self) -> int:
        return len(self.pending)

    def loaded(self, key: str) -> Any:
        """The on-disk (loaded effective document) value of a dotted key, with
        no pending overlay — the baseline a Change's `old` is measured against,
        so reverting a field to it cleanly drops the queued edit."""
        return policies_toml.get_dotted(self.data.doc, key)

    def effective(self, key: str) -> Any:
        """Current value of a dotted key: newest pending edit wins, else the
        loaded baseline. For display. No disk read."""
        for c in reversed(self.pending):
            if c.key == key:
                return None if c.new is _UNSET else c.new
        return self.loaded(key)


# ----- read boundary --------------------------------------------------------


def load_state(ctx: SteamContext | None = None) -> WizardState:
    """Build the full editor state from disk. Drift is NOT computed here (it is
    render-coupled and lives in the UI layer).

    Degrades gracefully with no Steam install (discovery raising
    FileNotFoundError): `steam_found` is False and games/users/tools are empty,
    but the policy document still loads so global defaults stay editable."""
    if ctx is None:
        try:
            ctx = discovery.discover(steam_root=steam_root())
        except FileNotFoundError:
            ctx = None
    steam_found = ctx is not None

    engine = policy.load(policy_paths())
    doc = policies_toml.render_effective_doc(engine)

    games: list[GameRow] = []
    users: tuple = ()
    tools: tuple = ()
    if steam_found:
        types = _appinfo.appinfo_types()
        for app in _installed_games(ctx):
            app_type = types.get(app.appid)
            pol = policy.resolve(engine, app.appid, app_type)
            games.append(GameRow(
                appid=app.appid,
                name=app.name,
                app_type=app_type,
                policy_compat=pol.compat_tool if pol else None,
                policy_launch=pol.launch_options if pol else None,
                ignored=bool(pol and pol.ignore),
            ))
        users = tuple(discovery.list_users(ctx))
        tools = tuple(compat_tools.list_compat_tools(ctx))

    target_users = policies_toml.get_dotted(doc, "general.target_users") or []
    max_backups = policies_toml.get_dotted(doc, "general.max_backups")
    data = WizardData(
        games=tuple(games),
        users=users,
        tools=tools,
        games_compat=policies_toml.get_dotted(doc, "games.compat_tool"),
        games_launch=policies_toml.get_dotted(doc, "games.launch_options"),
        apps_compat=policies_toml.get_dotted(doc, "applications.compat_tool"),
        apps_launch=policies_toml.get_dotted(doc, "applications.launch_options"),
        target_users=tuple(str(u) for u in target_users),
        max_backups=int(max_backups) if max_backups is not None else 20,
        ignored_appids=frozenset(_read_ignored_from_user_doc()),
        steam_found=steam_found,
        doc=doc,
    )
    return WizardState(data=data, pending=())


# ----- reducers (pure: (state, value) -> state) -----------------------------


def _fold(state: WizardState, *changes: Change) -> WizardState:
    merged = _merge_pending(list(state.pending), list(changes))
    return replace(state, pending=tuple(merged))


def set_compat_tool(state: WizardState, scope: str, value: str | None) -> WizardState:
    """Set `<scope>.compat_tool`. `value=None` clears the key (Steam default)."""
    key = f"{scope}.compat_tool"
    new = _UNSET if value is None else value
    return _fold(state, Change(key, state.loaded(key), new))


def set_launch_options(state: WizardState, scope: str, value: str | None) -> WizardState:
    """Set `<scope>.launch_options`. Empty/None clears the key."""
    key = f"{scope}.launch_options"
    if value is None:
        new: Any = _UNSET
    else:
        stripped = value.strip()
        new = stripped if stripped else _UNSET
    return _fold(state, Change(key, state.loaded(key), new))


def set_target_users(state: WizardState, spec: list[str]) -> WizardState:
    """Set `general.target_users` to a spec list (`['active']`, `['*']`, or
    explicit account names)."""
    current = state.loaded("general.target_users") or []
    old_list = list(current) if isinstance(current, list) else []
    return _fold(state, Change("general.target_users", old_list, _toml_array(list(spec))))


def set_max_backups(state: WizardState, raw: str | int) -> WizardState:
    """Set `general.max_backups`. Invalid input (non-int or < 1) is rejected by
    returning the state unchanged (mirrors the classic `prompt_int minimum=1`)."""
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError):
        return state
    if value < 1:
        return state
    return _fold(state, Change("general.max_backups", state.loaded("general.max_backups"), value))


def _ignore_change(state: WizardState, appid: str, want: bool) -> Change:
    """A Change moving `overrides.<appid>.ignore` from its loaded user-doc
    baseline to `want`. A `want` equal to the baseline yields a no-op Change
    that `_merge_pending` drops."""
    loaded_ignored = appid in state.data.ignored_appids
    old = True if loaded_ignored else None
    new = True if want else _UNSET
    return Change(f"overrides.{appid}.ignore", old, new)


def set_ignored(state: WizardState, selected: set[str]) -> WizardState:
    """Set the full ignore selection over the installed games, each diffed
    against the loaded user-doc baseline. Games returned to their baseline drop
    back out of pending."""
    selected = set(selected)
    changes = [_ignore_change(state, g.appid, g.appid in selected)
               for g in state.data.games]
    return _fold(state, *changes)


def _effective_ignored(state: WizardState) -> set[str]:
    result = set(state.data.ignored_appids)
    for c in state.pending:
        if c.key.startswith("overrides.") and c.key.endswith(".ignore"):
            appid = c.key[len("overrides."):-len(".ignore")]
            if c.new is _UNSET:
                result.discard(appid)
            elif c.new is True:
                result.add(appid)
    return result


def toggle_ignore(state: WizardState, appid: str) -> WizardState:
    """Flip one game's ignore flag; toggling back to the baseline drops it."""
    want = appid not in _effective_ignored(state)
    return _fold(state, _ignore_change(state, appid, want))


def effective_value(state: WizardState, key: str) -> Any:
    return state.effective(key)


def discard(state: WizardState) -> WizardState:
    """Drop all queued edits."""
    return replace(state, pending=())


# ----- write boundary -------------------------------------------------------


def apply(state: WizardState) -> int:
    """Write the queued edits to the user policy file. Returns the count."""
    _apply_changes(list(state.pending))
    return len(state.pending)


def can_reset() -> bool:
    """True when a user policy file exists to delete."""
    return policies_toml.user_path().exists()


def reset() -> None:
    """Delete the user policy file (revert to factory defaults), if present."""
    p = policies_toml.user_path()
    if p.exists():
        p.unlink()
