"""Pure, front-end-agnostic core for the ScopeBuddy dashboard.

Turns the installed games plus their launch options into the ordered row
model the ScopeBuddy TUI renders. It reads state through
`io.scopebuddy.observe` and returns plain `ScbRow` values, importing only
dataclasses/pathlib, `io.scopebuddy`, and `models` — no Rich, Typer, Textual,
or questionary — so the classification logic stays unit-testable without a
terminal and without touching the real Steam install.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from steam_manager.io.scopebuddy import observe
from steam_manager.models import SteamApp


@dataclass(frozen=True)
class ScbRow:
    """One dashboard row: an installed game or an orphan config file."""
    appid: str            # game appid, or the conf stem for orphan rows
    name: str             # game name, or "<stem>.conf" for orphan rows
    status: str           # "active" | "missing" | "inactive" | "orphan"
    conf_path: Path       # <scb_dir>/<appid|stem>.conf (existence NOT implied)
    install_path: str = ""
    compatdata_path: str = ""


def load_rows(
    scb_dir: Path,
    games: list[SteamApp],
    launch_options: dict[str, str | None],
) -> list[ScbRow]:
    """Build the dashboard rows for the ScopeBuddy TUI.

    Game rows come first, sorted by `name.lower()`, then orphan rows sorted by
    conf stem. Status is derived from `observe`:
    `active` = scopebuddy in launch options AND conf exists; `missing` =
    scopebuddy in launch options AND conf absent; `inactive` = every other
    installed game; `orphan` = a conf file with no installed game.
    """
    obs = observe(scb_dir, [g.appid for g in games], launch_options)

    rows: list[ScbRow] = []
    for game in sorted(games, key=lambda a: a.name.lower()):
        if game.appid in obs.games_with_scb_launch:
            status = "missing" if game.appid in obs.missing_configs else "active"
        else:
            status = "inactive"
        rows.append(ScbRow(
            appid=game.appid,
            name=game.name,
            status=status,
            conf_path=scb_dir / f"{game.appid}.conf",
            install_path=str(game.install_path),
            compatdata_path=str(game.compatdata_path),
        ))

    for stem in obs.orphan_configs:
        rows.append(ScbRow(
            appid=stem,
            name=f"{stem}.conf",
            status="orphan",
            conf_path=scb_dir / f"{stem}.conf",
        ))

    return rows
