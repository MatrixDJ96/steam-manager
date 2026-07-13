"""Compute a restore preview: what changes would result from extracting
an archive's contents on top of the current on-disk state.

Each change dict is shaped to be drop-in compatible with
`render.diff_table_str`, the same renderer used by `steam-manager diff`:

    {appid, name, field, old, new, user, compatdata_path, install_path}

The semantic difference from `apply`-time drift:
- `old` = current on-disk value (will be OVERWRITTEN by restore)
- `new` = value from the archive (will be RESTORED)

This module reads the archive into a tempdir, parses the relevant VDF
sections, and diffs them against the live files. The archive is never
mutated, and the on-disk files are never touched here.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from steam_manager.io import backups, config_vdf, discovery, localconfig_vdf, shortcuts_vdf
from steam_manager.io._vdf_util import ci_get
from steam_manager.models import SteamApp, SteamContext, SteamUser

# Marks "file exists but can't be parsed" (vs "file absent" = None) in the
# shortcuts diff. Carried in a `(_UNREADABLE, raw_bytes)` pair so two
# differently-corrupt files still compare unequal and the change row shows.
_UNREADABLE = object()


def _is_unreadable(data) -> bool:
    return isinstance(data, tuple) and bool(data) and data[0] is _UNREADABLE


def _entry_compat_name(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    return name if name else None


def _entry_launch_options(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    return entry.get("LaunchOptions")


def _change(appid: str, apps_by_id: dict[str, SteamApp], *,
            field: str, old, new, user: str | None) -> dict:
    """Build one `render.diff_table_str`-shaped change dict, resolving the
    app's display name and link paths (falling back to '?' if it's gone)."""
    app = apps_by_id.get(appid)
    return {
        "appid": appid,
        "name": app.name if app else "?",
        "compatdata_path": str(app.compatdata_path) if app else "",
        "install_path": str(app.install_path) if app else "",
        "field": field, "old": old, "new": new, "user": user,
    }


def _compat_diff(archive_config: Path, ctx: SteamContext,
                 apps_by_id: dict[str, SteamApp]) -> list[dict]:
    """System-wide compat-tool changes between the live config.vdf and the
    archive's. The appid '0' default-tool slot is skipped so restoring a
    checkpoint never silently changes Steam's global default."""
    current_map = config_vdf.load_compat_map_from_file(ctx.root / "config" / "config.vdf")
    archive_map = config_vdf.load_compat_map_from_file(archive_config)
    out: list[dict] = []
    for appid in sorted(set(current_map) | set(archive_map)):
        if appid == "0":
            continue
        cur = _entry_compat_name(current_map.get(appid))
        arc = _entry_compat_name(archive_map.get(appid))
        if cur != arc:
            out.append(_change(appid, apps_by_id, field="compat_tool",
                               old=cur, new=arc, user=None))
    return out


def _launch_diff(archived_localconfigs: dict[str, Path],
                 user_by_name: dict[str, SteamUser],
                 apps_by_id: dict[str, SteamApp]) -> list[dict]:
    """Per-user launch-option changes between each live localconfig.vdf and the
    archive's. Users no longer present locally are skipped."""
    out: list[dict] = []
    for uname, archive_lc in archived_localconfigs.items():
        if uname not in user_by_name:
            continue
        disk_lc = user_by_name[uname].userdata_dir / "config" / "localconfig.vdf"
        current_apps = localconfig_vdf.load_apps_section_from_file(disk_lc)
        archive_apps = (localconfig_vdf.load_apps_section_from_file(archive_lc)
                        if archive_lc.exists() else {})
        for appid in sorted(set(current_apps) | set(archive_apps)):
            cur = _entry_launch_options(current_apps.get(appid))
            arc = _entry_launch_options(archive_apps.get(appid))
            if cur != arc:
                out.append(_change(appid, apps_by_id, field="launch_options",
                                   old=cur, new=arc, user=uname))
    return out


def _load_shortcuts(path: Path):
    """Parsed shortcuts.vdf dict, None when absent, an `(_UNREADABLE, bytes)`
    pair on a parse failure (keyed by content, so two differently-corrupt
    files stay distinct in the diff)."""
    if not path.exists():
        return None
    try:
        return shortcuts_vdf.load(path)
    except Exception:  # noqa: BLE001 — any parse failure means "unreadable"
        try:
            raw = path.read_bytes()
        except OSError:
            raw = None
        return (_UNREADABLE, raw)


def _shortcuts_label(data) -> str | None:
    """Compact content label for one side of a shortcuts diff: entry count
    plus the AppNames (truncated), 'unreadable' for a corrupt file."""
    if data is None:
        return None
    if _is_unreadable(data):
        return "unreadable"
    entries = ci_get(data, "shortcuts") or {}
    names = sorted(
        str(ci_get(e, "appname") or "?")
        for e in entries.values() if isinstance(e, dict)
    )
    label = f"{len(names)} shortcut(s)"
    if names:
        joined = ", ".join(names)
        if len(joined) > 40:
            joined = joined[:39] + "…"
        label += f" — {joined}"
    return label


def _shortcuts_diff(archived_shortcuts: dict[str, Path],
                    user_by_name: dict[str, SteamUser]) -> list[dict]:
    """Per-user non-Steam shortcuts changes between each live shortcuts.vdf
    and the archive's. One row per user (the file is restored wholesale, so
    the preview is a content summary, not a per-entry diff)."""
    out: list[dict] = []
    for uname, archive_sc in archived_shortcuts.items():
        if uname not in user_by_name:
            continue
        cur = _load_shortcuts(shortcuts_vdf.shortcuts_path(user_by_name[uname]))
        arc = _load_shortcuts(archive_sc)
        if cur == arc:
            continue
        out.append({
            "appid": "-", "name": "shortcuts.vdf",
            "compatdata_path": "", "install_path": "",
            "field": "shortcuts",
            "old": _shortcuts_label(cur), "new": _shortcuts_label(arc),
            "user": uname,
        })
    return out


def _scb_content(path: Path):
    """Raw bytes of a ScopeBuddy conf for equality comparison: None when the
    file is absent, `_UNREADABLE` when it exists but can't be read."""
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return _UNREADABLE


def _scb_label(path: Path) -> str:
    """Compact content label for one side of a ScopeBuddy conf diff: 'absent'
    when missing, a line count otherwise, 'unreadable' on a read error."""
    if not path.exists():
        return "absent"
    try:
        return f"{len(path.read_text().splitlines())} line(s)"
    except OSError:
        return "unreadable"


def _scb_diff(archived_scb: dict[str, Path], scb_dir: Path) -> list[dict]:
    """Per-stem ScopeBuddy .conf changes between each live config and the
    archive's. One row per differing conf (the file is restored wholesale, so
    the preview is a line-count summary, not a per-line diff)."""
    out: list[dict] = []
    for stem, archive_conf in sorted(archived_scb.items()):
        live = scb_dir / f"{stem}.conf"
        if _scb_content(live) == _scb_content(archive_conf):
            continue
        out.append({
            "appid": stem, "name": f"{stem}.conf",
            "compatdata_path": "", "install_path": "",
            "field": "scb_conf",
            "old": _scb_label(live), "new": _scb_label(archive_conf),
            "user": None,
        })
    return out


def compute_restore_diff(
    archive_path: Path,
    ctx: SteamContext,
    users: list[SteamUser],
    users_in_archive: list[str],
    *,
    shortcuts_users: list[str] = (),
    scb_stems: list[str] = (),
    scb_dir: Path | None = None,
) -> list[dict]:
    """Diff the archive's contents against the current on-disk state.

    Returns a list of change dicts compatible with `render.diff_table_str`.
    The list is empty when restoring would not change anything.

    `users_in_archive` is the list of account names whose `localconfig.vdf`
    was packed into the checkpoint (typically from `chosen["manifest"]
    .get("users", [])`); `shortcuts_users` the ones whose `shortcuts.vdf`
    was. Users present in the archive but no longer in `users` are skipped
    silently. `scb_stems` is the list of ScopeBuddy conf stems packed as
    `scopebuddy/<stem>.conf` members; each is diffed against
    `scb_dir/<stem>.conf` (both keyword args are supplied together).
    """
    changes: list[dict] = []
    apps_by_id = {a.appid: a for a in discovery.list_apps(ctx)}
    user_by_name = {u.account_name: u for u in users}

    with tempfile.TemporaryDirectory(prefix="sm-restore-diff-") as tmp:
        tmp_dir = Path(tmp)
        archive_config = tmp_dir / "config.vdf"
        targets: dict[str, Path] = {"config.vdf": archive_config}
        archived_localconfigs: dict[str, Path] = {}
        for uname in users_in_archive:
            dest = tmp_dir / "users" / uname / "localconfig.vdf"
            targets[f"users/{uname}/localconfig.vdf"] = dest
            archived_localconfigs[uname] = dest
        archived_shortcuts: dict[str, Path] = {}
        for uname in shortcuts_users:
            dest = tmp_dir / "users" / uname / "shortcuts.vdf"
            targets[f"users/{uname}/shortcuts.vdf"] = dest
            archived_shortcuts[uname] = dest
        archived_scb: dict[str, Path] = {}
        for stem in scb_stems:
            dest = tmp_dir / "scopebuddy" / f"{stem}.conf"
            targets[f"scopebuddy/{stem}.conf"] = dest
            archived_scb[stem] = dest

        extracted = backups.extract_checkpoint(archive_path, targets)

        if "config.vdf" in extracted:
            changes += _compat_diff(archive_config, ctx, apps_by_id)
        changes += _launch_diff(archived_localconfigs, user_by_name, apps_by_id)
        changes += _shortcuts_diff(archived_shortcuts, user_by_name)
        if scb_dir is not None:
            changes += _scb_diff(archived_scb, scb_dir)

    return changes
