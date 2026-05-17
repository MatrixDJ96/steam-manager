"""Core data structures shared across io/ and cli/.

These dataclasses cross every layer of the project (I/O, policy, CLI),
so they live in a single, dependency-free module to keep import direction
one-way and avoid cycles. Anything that doesn't cross layers stays
co-located with the module that owns it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class SteamUser:
    account_name: str
    steamid64: str
    steamid3: str
    userdata_dir: Path
    is_active: bool


@dataclass
class SteamApp:
    appid: str
    name: str
    library: Path
    state_flags: int
    installdir: str = ""

    @property
    def installed(self) -> bool:
        return bool(self.state_flags & 4)

    @property
    def install_path(self) -> Path:
        """Filesystem path of the installed game content."""
        return self.library / "steamapps" / "common" / self.installdir

    @property
    def compatdata_path(self) -> Path:
        """Filesystem path of the Proton compatdata folder for this app."""
        return self.library / "steamapps" / "compatdata" / self.appid


@dataclass
class SteamContext:
    root: Path
    libraries: list[Path] = field(default_factory=list)
    library_labels: dict[str, str] = field(default_factory=dict)
    users: list[SteamUser] = field(default_factory=list)


@dataclass
class ShortcutsFile:
    user: SteamUser
    path: Path
    exists: bool


@dataclass(frozen=True)
class CompatTool:
    tech_name: str
    display_name: str
    source: Literal["custom", "official", "builtin"]
    install_path: Path | None
