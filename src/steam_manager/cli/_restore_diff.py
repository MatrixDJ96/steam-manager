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
from steam_manager.models import SteamContext, SteamUser


def _entry_compat_name(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    return name if name else None


def _entry_launch_options(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    return entry.get("LaunchOptions")


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
        targets: dict[str, Path] = {}
        archive_config = tmp_dir / "config.vdf"
        targets["config.vdf"] = archive_config

        archived_localconfigs: dict[str, Path] = {}
        for uname in users_in_archive:
            arch_name = f"users/{uname}/localconfig.vdf"
            dest = tmp_dir / "users" / uname / "localconfig.vdf"
            targets[arch_name] = dest
            archived_localconfigs[uname] = dest

        extracted = backups.extract_checkpoint(archive_path, targets)

        # --- Compat tool diff (system-wide) -------------------------------
        if "config.vdf" in extracted:
            disk_config = ctx.root / "config" / "config.vdf"
            current_map = config_vdf.load_compat_map_from_file(disk_config)
            archive_map = config_vdf.load_compat_map_from_file(archive_config)
            for appid in sorted(set(current_map.keys()) | set(archive_map.keys())):
                if appid == "0":
                    # Steam's default-tool slot; treat specially or skip.
                    # We skip it: restoring a checkpoint shouldn't surprise
                    # the user with a change to the global default.
                    continue
                cur = _entry_compat_name(current_map.get(appid))
                arc = _entry_compat_name(archive_map.get(appid))
                if cur == arc:
                    continue
                app = apps_by_id.get(appid)
                changes.append({
                    "appid": appid,
                    "name": app.name if app else "?",
                    "compatdata_path": str(app.compatdata_path) if app else "",
                    "install_path": str(app.install_path) if app else "",
                    "field": "compat_tool",
                    "old": cur,
                    "new": arc,
                    "user": None,
                })

        # --- Launch options diff (per user) -------------------------------
        for uname, archive_lc in archived_localconfigs.items():
            if uname not in user_by_name:
                continue  # account no longer exists locally
            user = user_by_name[uname]
            disk_lc = user.userdata_dir / "config" / "localconfig.vdf"
            current_apps = localconfig_vdf.load_apps_section_from_file(disk_lc)
            archive_apps = (
                localconfig_vdf.load_apps_section_from_file(archive_lc)
                if archive_lc.exists() else {}
            )
            for appid in sorted(set(current_apps.keys()) | set(archive_apps.keys())):
                cur = _entry_launch_options(current_apps.get(appid))
                arc = _entry_launch_options(archive_apps.get(appid))
                if cur == arc:
                    continue
                app = apps_by_id.get(appid)
                changes.append({
                    "appid": appid,
                    "name": app.name if app else "?",
                    "compatdata_path": str(app.compatdata_path) if app else "",
                    "install_path": str(app.install_path) if app else "",
                    "field": "launch_options",
                    "old": cur,
                    "new": arc,
                    "user": uname,
                })

    return changes
