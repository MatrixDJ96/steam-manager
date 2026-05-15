"""Checkpoint orchestration: build manifest + create archive + prune.

The atomic `.tar.gz` primitive lives in `io/backups.py`; this module is
the CLI-side wrapper that assembles the standardized manifest format
used by `apply`, `clear`, `backup`, and `shortcuts edit`. Centralizing
the manifest schema here prevents the four call sites from drifting
apart (which they had started to: `restore` discovers checkpoints by
manifest fields, so any inconsistency would break rollback).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from steam_manager.cli._common import backup_root, iso_timestamp
from steam_manager.io import backups
from steam_manager.models import SteamContext, SteamUser


def build_steam_files(
    ctx: SteamContext, users: list[SteamUser]
) -> tuple[dict[str, Path], list[str]]:
    """Build (files, user_names) for the standard Steam checkpoint shape.

    `files` maps archive-name -> filesystem-path:
      - 'config.vdf' if present at ctx.root/config/config.vdf
      - 'users/<name>/localconfig.vdf' for each user with one on disk
    `user_names` lists the accounts whose localconfig was included.
    """
    files: dict[str, Path] = {}
    config_path = ctx.root / "config" / "config.vdf"
    if config_path.is_file():
        files["config.vdf"] = config_path
    user_names: list[str] = []
    for u in users:
        local_path = u.userdata_dir / "config" / "localconfig.vdf"
        if local_path.is_file():
            files[f"users/{u.account_name}/localconfig.vdf"] = local_path
            user_names.append(u.account_name)
    return files, user_names


def make_checkpoint(
    trigger: str,
    files: dict[str, Path],
    *,
    users: list[str] = (),
    max_backups: int | None = None,
) -> Path:
    """Atomic .tar.gz checkpoint with the standardized manifest.

    Returns the archive path. The manifest fields (`trigger`, `system`,
    `users`, `files`) are exactly what `restore` expects; do not invent
    new ones without also teaching restore to handle them.

    Note: the manifest does NOT store the drift list. Restore computes
    a fresh diff on demand against the live on-disk state (see
    `cli/_restore_diff.py`), which is always more accurate than a
    snapshot frozen at apply time.

    `max_backups`, if given, triggers pruning of older archives.
    """
    ts = iso_timestamp()
    root = backup_root()
    manifest = {
        "created_at": _dt.datetime.now().isoformat(),
        "trigger": trigger,
        "system": "config.vdf" in files,
        "users": list(users),
        "files": list(files.keys()),
    }
    archive = backups.create_checkpoint(root, ts, files, manifest)
    if max_backups is not None:
        backups.prune_checkpoints(root, max_backups)
    return archive
