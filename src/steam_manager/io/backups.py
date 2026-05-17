"""Atomic checkpoint archives (.tar.gz) for reversible destructive operations.

A checkpoint is a single `<timestamp>.tar.gz` containing `manifest.json`
plus every snapshotted file. The archive is written to a temp file then
atomically renamed so a crash mid-write cannot leave a partial checkpoint.
This is the format used by `apply`, `clear`, `backup`, and `shortcuts edit`
to enable rollback via `restore`.
"""
from __future__ import annotations

import json
import os
import shutil
import tarfile
from io import BytesIO
from pathlib import Path


def create_checkpoint(
    root: Path,
    timestamp: str,
    files: dict[str, Path],
    manifest: dict,
) -> Path:
    """Create a .tar.gz archive containing all `files` plus manifest.json.

    `files`: {archive-name: absolute-source-path}.
    `manifest`: dict serialized as manifest.json inside the archive.

    Written to a temp file then atomically renamed, to avoid partial
    checkpoints if the process crashes mid-write.

    Returns the path of the created archive.
    """
    root.mkdir(parents=True, exist_ok=True)
    archive_path = root / f"{timestamp}.tar.gz"
    tmp = root / f".{timestamp}.tar.gz.tmp"
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_bytes)
            tar.addfile(info, BytesIO(manifest_bytes))
            for name, src in files.items():
                tar.add(src, arcname=name)
        tmp.replace(archive_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    # The archive contains per-user `localconfig.vdf` (account names,
    # Steam IDs, LastPlayed, friend graph fragments) and any user-pasted
    # `LaunchOptions` (sometimes embedding API keys, Wine prefix tokens).
    # World-readable would leak that to other local users on a shared box.
    os.chmod(archive_path, 0o600)
    return archive_path


def list_checkpoints(root: Path) -> list[dict]:
    """List available checkpoints.

    Returns [{timestamp, path, manifest, files}] sorted lexicographically
    (oldest first).
    """
    if not root.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(root.glob("*.tar.gz")):
        timestamp = p.name[:-len(".tar.gz")]
        manifest: dict = {}
        members: list[str] = []
        try:
            with tarfile.open(p, "r:gz") as tar:
                members = [m.name for m in tar.getmembers()]
                if "manifest.json" in members:
                    mf = tar.extractfile("manifest.json")
                    if mf:
                        manifest = json.loads(mf.read().decode("utf-8"))
        except (OSError, tarfile.TarError, json.JSONDecodeError):
            manifest = {}
            members = []
        out.append({
            "timestamp": timestamp,
            "path": str(p),
            "manifest": manifest,
            "files": [m for m in members if m != "manifest.json"],
        })
    return out


def extract_checkpoint(archive_path: Path, targets: dict[str, Path]) -> list[str]:
    """Extract the files listed in `targets` from the archive.

    `targets`: {archive-name: absolute-destination-path}.

    Returns the list of archive-names successfully extracted; targets not
    found in the archive are silently skipped.

    Each file is written to a sibling `.tmp` and renamed atomically via
    `os.replace`. A crash mid-restore can leave fewer files restored than
    intended (impossible to make a multi-file restore truly transactional
    without two-phase locking), but each individual destination is never
    left half-written or corrupted.

    Symlinked archive members (`issym`/`islnk`) are rejected — they have no
    legitimate use in our checkpoints and would otherwise let a malicious
    archive escape its containment to attacker-chosen paths.
    """
    extracted: list[str] = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for name, dest in targets.items():
            try:
                member = tar.getmember(name)
            except KeyError:
                continue
            if member.issym() or member.islnk():
                continue
            mf = tar.extractfile(member)
            if mf is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
            with tmp_dest.open("wb") as out:
                shutil.copyfileobj(mf, out)
            os.replace(tmp_dest, dest)
            extracted.append(name)
    return extracted


def prune_checkpoints(root: Path, limit: int) -> list[Path]:
    """Keep the last `limit` .tar.gz archives in root (lexicographic order).
    Removes the oldest; returns the list of removed paths."""
    if not root.is_dir():
        return []
    archives = sorted(root.glob("*.tar.gz"))
    if len(archives) <= limit:
        return []
    to_remove = archives[:len(archives) - limit]
    for p in to_remove:
        p.unlink()
    return to_remove
