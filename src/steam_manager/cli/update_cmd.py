"""`steam-manager update` — self-update the installed binary.

Python owns *discovery* (GitHub API call, version compare, release-notes
rendering); the actual download + SHA-256 verify + atomic replace is
delegated to a fresh copy of `scripts/install.sh` fetched from main on
every update. This keeps install logic in one place (the script) and lets
old binaries auto-heal when the release-asset layout changes upstream.

Linux-only by design: `os.replace` over a running binary works because of
unlink-while-mmap semantics; install.sh enforces the platform check.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import typer
from rich.markdown import Markdown

from steam_manager import __version__, render
from steam_manager.cli._common import ExitCode, update_state_path
from steam_manager.cli.app import app
from steam_manager.io import github_releases

_INSTALL_SH_URL = (
    "https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh"
)
_MAX_NOTES_LINES = 40
_MAX_NOTES_BYTES = 4096


def _refuse_if_not_frozen() -> None:
    """Update only makes sense for the PyInstaller binary."""
    if not getattr(sys, "frozen", False):
        render.error(
            "This command only updates the PyInstaller binary.\n"
            "You're running from source — use [bold]pip install -U[/bold] "
            "or [bold]git pull[/bold] instead."
        )
        raise typer.Exit(ExitCode.PARSE_ERROR)


def _resolve_binary() -> Path:
    """The currently-running binary path. Refuses if its dir is unwritable."""
    binary = Path(os.path.realpath(sys.executable))
    if not os.access(binary.parent, os.W_OK):
        render.error(
            f"Cannot write to [dim]{binary.parent}[/dim].\n"
            "If this is a system-wide install, re-run with [bold]sudo[/bold] "
            "or use your package manager."
        )
        raise typer.Exit(ExitCode.WRITE_ERROR)
    return binary


def _truncate_body(body: str, html_url: str) -> str:
    """Cap release notes to a reasonable size, with a link to the full page."""
    if not body:
        return ""
    lines = body.splitlines()
    truncated = False
    if len(lines) > _MAX_NOTES_LINES:
        lines = lines[:_MAX_NOTES_LINES]
        truncated = True
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > _MAX_NOTES_BYTES:
        # Re-truncate by bytes; markdown rendering tolerates a chopped tail.
        text = text.encode("utf-8")[:_MAX_NOTES_BYTES].decode("utf-8", errors="ignore")
        truncated = True
    if truncated:
        text = text + f"\n\n*…truncated. Full notes: {html_url}*"
    return text


def _render_release_notes(release: github_releases.ReleaseInfo) -> None:
    """Render the release `body` as a Rich Markdown panel."""
    body = _truncate_body(release.body, release.html_url)
    if not body.strip():
        return
    md = Markdown(body)
    render.console.print(render._panel(md, f"Release notes — {release.tag}"))


def _delete_cache() -> None:
    """Best-effort: drop the notifier cache after a successful update."""
    try:
        update_state_path().unlink(missing_ok=True)
    except OSError:
        pass


def _post_install_version(binary: Path) -> str | None:
    """Re-exec the (now-replaced) binary with --version. Returns its stdout or None."""
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


@app.command(name="update", rich_help_panel="Extras")
def update_cmd(
    check: bool = typer.Option(
        False, "--check", help="Only check for a new version; don't install.",
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip confirmation prompt.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-install even if already on the latest version.",
    ),
) -> None:
    """Update steam-manager to the latest GitHub release."""
    _refuse_if_not_frozen()
    binary = _resolve_binary()

    try:
        release = github_releases.fetch_latest_release()
    except github_releases.GitHubReleaseError as exc:
        render.error(f"Could not check for updates: {exc}")
        raise typer.Exit(ExitCode.WRITE_ERROR)

    cmp = github_releases.compare_versions(__version__, release.version)
    on_latest = cmp >= 0  # current >= latest (covers downgrade-from-prerelease too)

    if check:
        if on_latest:
            render.success(f"Up to date ([bold]{__version__}[/bold]).")
        else:
            render.info(
                f"Update available: [bold green]{release.version}[/bold green] "
                f"(current: [bold]{__version__}[/bold])\n"
                f"[dim]{release.html_url}[/dim]"
            )
        _delete_cache()
        raise typer.Exit(ExitCode.OK)

    if on_latest and not force:
        render.success(f"Already on latest ([bold]{__version__}[/bold]).")
        _delete_cache()
        raise typer.Exit(ExitCode.OK)

    render.info(
        f"steam-manager [bold]{__version__}[/bold] → "
        f"[bold green]{release.version}[/bold green]"
    )
    _render_release_notes(release)

    if not yes and not typer.confirm(
        f"Install {release.version}?", default=True,
    ):
        render.info("Cancelled.")
        raise typer.Exit(ExitCode.OK)

    # Fetch a fresh install.sh from main; self-heals across release-format changes.
    try:
        script_text = github_releases.fetch_text(_INSTALL_SH_URL)
    except github_releases.GitHubReleaseError as exc:
        render.error(f"Could not fetch installer script: {exc}")
        raise typer.Exit(ExitCode.WRITE_ERROR)

    fd, tmp_path_str = tempfile.mkstemp(prefix="steam-manager-install-", suffix=".sh")
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    try:
        tmp_path.write_text(script_text)
        env = {
            **os.environ,
            "STEAM_MANAGER_VERSION": release.tag,
            "STEAM_MANAGER_INSTALL_DIR": str(binary.parent),
            "STEAM_MANAGER_QUIET": "1",
        }
        render.info(f"Running installer for [bold]{release.tag}[/bold]...")
        try:
            result = subprocess.run(
                ["bash", str(tmp_path)], env=env, check=False,
            )
        except FileNotFoundError:
            render.error(
                "bash not found. The updater requires bash + curl/wget.\n"
                "Install bash or re-run scripts/install.sh manually."
            )
            raise typer.Exit(ExitCode.WRITE_ERROR)

        if result.returncode != 0:
            render.error(
                f"Installer exited with code [bold]{result.returncode}[/bold]. "
                "The binary was NOT replaced."
            )
            raise typer.Exit(ExitCode.WRITE_ERROR)
    finally:
        tmp_path.unlink(missing_ok=True)

    # Confirm the swap actually took: a subprocess exec resolves to the new file.
    new_version_output = _post_install_version(binary)
    if new_version_output is None or release.version not in new_version_output:
        render.error(
            "Installer reported success but the binary's --version did not "
            f"advance to {release.version}. Got: {new_version_output!r}"
        )
        raise typer.Exit(ExitCode.WRITE_ERROR)

    _delete_cache()
    render.success(f"Updated [bold]{__version__}[/bold] → [bold green]{release.version}[/bold green].")
    raise typer.Exit(ExitCode.OK)
