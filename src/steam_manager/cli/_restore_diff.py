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

from steam_manager.io import backups, config_vdf, discovery, localconfig_vdf
from steam_manager.models import SteamApp, SteamContext, SteamUser


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


def compute_restore_diff(
    archive_path: Path,
    ctx: SteamContext,
    users: list[SteamUser],
    users_in_archive: list[str],
) -> list[dict]:
    """Diff the archive's contents against the current on-disk state.

    Returns a list of change dicts compatible with `render.diff_table_str`.
    The list is empty when restoring would not change anything.

    `users_in_archive` is the list of account names whose `localconfig.vdf`
    was packed into the checkpoint (typically from `chosen["manifest"]
    .get("users", [])`). Users present in the archive but no longer in
    `users` are skipped silently.
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

        extracted = backups.extract_checkpoint(archive_path, targets)

        if "config.vdf" in extracted:
            changes += _compat_diff(archive_config, ctx, apps_by_id)
        changes += _launch_diff(archived_localconfigs, user_by_name, apps_by_id)

    return changes
