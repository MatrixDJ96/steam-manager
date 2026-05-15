"""Target-user resolution: turn --user/--all-users flags into a user list.

These helpers translate the CLI's user-targeting flags into a concrete
list of `SteamUser` objects, honoring `target_users` from the policy
file as the default when no flag is passed.
"""
from __future__ import annotations

import typer

from steam_manager import render
from steam_manager.cli._common import ExitCode
from steam_manager.models import SteamUser


def resolve_target_users(users: list[SteamUser], target_spec: list[str]) -> list[SteamUser]:
    """Map a target_spec list to actual SteamUser objects."""
    if target_spec == ["active"]:
        return [u for u in users if u.is_active]
    if target_spec == ["*"]:
        return users
    return [u for u in users if u.account_name in target_spec]


def effective_target_spec(
    engine_default: list[str], user: str | None, all_users: bool,
) -> list[str]:
    """Resolve target_users: CLI flags override policies.toml.

    --user X         → [X]
    --all-users      → ["*"]
    (neither)        → engine_default (typically ["active"])
    --user + --all-users → mutually exclusive, exits 3.
    """
    if user and all_users:
        render.error("--user and --all-users are mutually exclusive.")
        raise typer.Exit(ExitCode.PARSE_ERROR)
    if user:
        return [user]
    if all_users:
        return ["*"]
    return engine_default


def target_users_banner(users: list[SteamUser], target_spec: list[str]) -> str:
    """Build a one-line Rich-markup banner listing the target users."""
    targets = resolve_target_users(users, target_spec)
    if not targets:
        return f"Target users: [red]no user matches {target_spec!r}[/red]"
    parts = []
    for u in targets:
        if u.is_active:
            parts.append(
                f"[cyan]user[/cyan]:[bold cyan]{u.account_name}[/bold cyan] "
                f"[dim](active)[/dim]"
            )
        else:
            parts.append(f"[cyan]user[/cyan]:[bold cyan]{u.account_name}[/bold cyan]")
    return "Target users: " + ", ".join(parts)
