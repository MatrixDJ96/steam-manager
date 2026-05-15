"""GitHub Releases API discovery for self-update.

Pure I/O layer: stdlib `urllib.request` + `json` only, zero new deps.
No Typer, no Rich. Returns plain dataclasses for the CLI layer to render.

The actual install/atomic-replace is delegated to `scripts/install.sh`
(see `cli/update_cmd.py`); this module only owns *discovery* (what
version is the latest, what does the release page link to, what are
the release notes).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request as _urllib_request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request

from steam_manager import __version__

DEFAULT_REPO = "MatrixDJ96/steam-manager"
_REPO_ENV = "STEAM_MANAGER_UPDATE_REPO"


class GitHubReleaseError(Exception):
    """Wraps urllib / json / format errors with a user-readable message."""


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str          # "v0.0.3"
    version: str      # "0.0.3"  (tag with leading "v" stripped)
    name: str         # GitHub release title
    body: str         # markdown release notes
    html_url: str     # human-readable release page


def _resolve_repo(repo: str | None) -> str:
    if repo is not None:
        return repo
    return os.environ.get(_REPO_ENV) or DEFAULT_REPO


def fetch_latest_release(
    repo: str | None = None, *, timeout: float = 5.0
) -> ReleaseInfo:
    """GET /repos/<repo>/releases/latest and parse into a ReleaseInfo.

    Raises GitHubReleaseError on any HTTP, JSON, or shape error.
    """
    target_repo = _resolve_repo(repo)
    url = f"https://api.github.com/repos/{target_repo}/releases/latest"
    req = Request(url, headers={
        # GitHub API rejects requests with no User-Agent.
        "User-Agent": f"steam-manager/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise GitHubReleaseError(
            f"GitHub API returned HTTP {exc.code} for {url}"
        ) from exc
    except URLError as exc:
        raise GitHubReleaseError(
            f"network error contacting GitHub: {exc.reason}"
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GitHubReleaseError(f"malformed response from GitHub: {exc}") from exc

    try:
        tag = data["tag_name"]
        html_url = data["html_url"]
    except (KeyError, TypeError) as exc:
        raise GitHubReleaseError(f"missing field in GitHub response: {exc}") from exc

    version = tag.lstrip("v")
    return ReleaseInfo(
        tag=tag,
        version=version,
        name=data.get("name") or tag,
        body=data.get("body") or "",
        html_url=html_url,
    )


def fetch_text(url: str, *, timeout: float = 5.0) -> str:
    """GET a plain-text resource. Used by cli/update_cmd.py to fetch install.sh."""
    req = Request(url, headers={"User-Agent": f"steam-manager/{__version__}"})
    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as exc:
        raise GitHubReleaseError(f"HTTP {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise GitHubReleaseError(f"network error fetching {url}: {exc.reason}") from exc
    except UnicodeDecodeError as exc:
        raise GitHubReleaseError(f"malformed text response: {exc}") from exc


# Version segment: contiguous digits, optional pre-release marker (rc/beta/alpha + digits).
_SEGMENT = re.compile(r"^(\d+)(?:[-.]?(rc|beta|alpha|dev|pre)\.?(\d*))?$", re.IGNORECASE)
_PRERELEASE_ORDER = {"dev": 0, "alpha": 1, "beta": 2, "rc": 3, "pre": 3, None: 4}


def _parse_version(v: str) -> tuple[tuple[int, int, int], ...]:
    """Parse "0.0.3-rc.1" / "v1.2.3" into a sortable tuple.

    Each segment becomes (numeric, prerelease_rank, prerelease_num).
    A bare "1.2.3" yields ((1,4,0), (2,4,0), (3,4,0)) — rank 4 is the
    "stable" sentinel so a bare version sorts above any pre-release of itself.
    """
    cleaned = v.lstrip("v").strip()
    if not cleaned:
        return ()
    out: list[tuple[int, int, int]] = []
    for raw in cleaned.replace("+", ".").split("."):
        m = _SEGMENT.match(raw)
        if not m:
            # Unrecognized segment — treat as 0 so we don't crash on weird tags.
            out.append((0, _PRERELEASE_ORDER[None], 0))
            continue
        num = int(m.group(1))
        pre = m.group(2)
        prenum = int(m.group(3)) if m.group(3) else 0
        rank = _PRERELEASE_ORDER.get(pre.lower() if pre else None, _PRERELEASE_ORDER[None])
        out.append((num, rank, prenum))
    return tuple(out)


def compare_versions(current: str, latest: str) -> int:
    """Return -1 / 0 / 1 for current < / == / > latest.

    Stdlib-only. Handles a leading "v", numeric dotted versions, and
    common pre-release suffixes (`-rc.1`, `-beta2`, `-alpha`). Pre-releases
    sort below their bare counterpart: `0.0.3-rc.1 < 0.0.3 < 0.0.4`.
    """
    a, b = _parse_version(current), _parse_version(latest)
    if a < b:
        return -1
    if a > b:
        return 1
    return 0
