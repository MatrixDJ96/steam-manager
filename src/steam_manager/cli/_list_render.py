"""Rendering helper for `steam-manager list` — the Games/Applications panels.

Kept out of `list_cmd` so the command stays a thin orchestrator (discover →
resolve targets → compute drift → render) and the table/column layout lives in
one focused, separately-testable place. Grouping mirrors
`policy.section_for_type`: every listable app resolves to 'games' or
'applications', and each non-empty group becomes its own aligned panel.
"""
from __future__ import annotations

from rich.console import Console

from steam_manager import policy, render
from steam_manager.io import config_vdf, localconfig_vdf
from steam_manager.models import SteamApp, SteamContext, SteamUser


def _disp_len(value: str | None, floor: int) -> int:
    """Display width of a cell value with a minimum floor; None shows as <none>."""
    return max(floor, len(value) if value else len("<none>"))


def render_app_groups(
    console: Console,
    ctx: SteamContext,
    listable: list[SteamApp],
    types: dict[str, str],
    target_users: list[SteamUser],
    drift_appids: set[str],
) -> None:
    """Print the installed apps as separate Games / Applications panels.

    Drift rows are bold, conforming rows dim. Column min-widths are shared
    across both panels so their borders and columns line up even though each
    panel sizes to its own content.
    """
    multi_user = len(target_users) > 1

    # Read each app's on-disk state once, reused by the width pass and the rows.
    compat_by_id = {a.appid: config_vdf.get_compat_tool(ctx, a.appid) for a in listable}
    launch_by_id = {
        a.appid: {u.account_name: localconfig_vdf.get_launch_options(u, a.appid)
                  for u in target_users}
        for a in listable
    }

    # Group by the policy section each app resolves through; unknown or missing
    # types resolve to 'games', so every listable app lands in exactly one group.
    groups: dict[str, list[SteamApp]] = {}
    for a in listable:
        section = policy.section_for_type(types.get(a.appid)) or "games"
        groups.setdefault(section, []).append(a)

    def _launch_header(u: SteamUser) -> str:
        return f"Launch ({u.account_name})" if multi_user else "LaunchOptions"

    # Shared min-widths so columns line up between the two content-sized panels.
    col_min = {
        "appid": max((len(a.appid) for a in listable), default=5),
        "name": max((len(a.name) for a in listable), default=4),
        "compat": max((_disp_len(compat_by_id[a.appid], 10) for a in listable), default=10),
    }
    launch_min = {
        u.account_name: max(
            len(_launch_header(u)),
            max((_disp_len(launch_by_id[a.appid][u.account_name], 0) for a in listable),
                default=0),
        )
        for u in target_users
    }

    def _table(subset: list[SteamApp]):
        table = render._make_inner_table()
        # AppID links to the Proton compatdata folder; Name to the install folder.
        table.add_column("AppID", justify="right", style="bold cyan", no_wrap=True,
                         min_width=col_min["appid"])
        table.add_column("Name", no_wrap=True, min_width=col_min["name"])
        table.add_column("CompatTool", no_wrap=True, min_width=col_min["compat"])
        for u in target_users:
            table.add_column(
                f"Launch ([cyan]{u.account_name}[/cyan])" if multi_user else "LaunchOptions",
                no_wrap=True, overflow="ellipsis", min_width=launch_min[u.account_name],
            )
        for a in subset:
            row = [
                render.link_cell(str(a.compatdata_path), a.appid),
                render.link_cell(str(a.install_path), a.name),
                compat_by_id[a.appid] or "[dim]<none>[/dim]",
            ]
            for u in target_users:
                row.append(launch_by_id[a.appid][u.account_name] or "[dim]<none>[/dim]")
            table.add_row(*row, style="bold" if a.appid in drift_appids else "dim")
        return table

    for section in ("games", "applications"):
        subset = groups.get(section)
        if subset:
            console.print(render._panel(_table(subset), render.SECTION_LABELS[section]))
