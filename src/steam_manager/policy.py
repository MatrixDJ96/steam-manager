"""Policy engine: TOML loading, per-section policies, AppID overrides."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Policy:
    """A policy may leave fields as None meaning 'don't enforce'."""
    compat_tool: str | None = None
    launch_options: str | None = None
    ignore: bool = False


@dataclass
class PolicyEngine:
    target_users: list[str]
    max_backups: int
    sections: dict[str, Policy]      # "games", "applications", ...
    overrides: dict[str, dict]       # appid -> partial Policy fields


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Deep merge: overlay wins on scalars, lists replace wholesale, dicts recurse."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(paths: list[Path]) -> PolicyEngine:
    """Load and merge N TOML files (missing paths are skipped)."""
    merged: dict = {}
    for p in paths:
        if not p.is_file():
            continue
        with p.open("rb") as f:
            merged = _deep_merge(merged, tomllib.load(f))

    general = merged.get("general", {})
    target_users = list(general.get("target_users", ["active"]))
    max_backups = general.get("max_backups", 20)
    if not isinstance(max_backups, int) or max_backups < 1:
        raise ValueError(
            f"general.max_backups must be a positive int, got {max_backups!r}"
        )

    sections: dict[str, Policy] = {}
    for section_name in ("games", "applications"):
        s = merged.get(section_name)
        if s is None:
            continue
        sections[section_name] = Policy(
            compat_tool=s.get("compat_tool"),
            launch_options=s.get("launch_options"),
        )

    overrides = merged.get("overrides", {})

    return PolicyEngine(
        target_users=target_users,
        max_backups=max_backups,
        sections=sections,
        overrides=overrides,
    )


# appinfo.vdf type -> policy section
_TYPE_TO_SECTION = {
    "game": "games",
    "beta": "games",
    "application": "applications",
}

# Types fully excluded (neither games nor apps).
_EXCLUDED_TYPES = {"dlc", "music", "tool", "demo", "video", "config",
                   "hardware", "series", "mod", "plugin", "media"}


def section_for_type(app_type: str | None) -> str | None:
    """Return the section name for a type, or None if the app is excluded.
    Missing/unknown types fall back to 'games'."""
    if app_type is None:
        return "games"
    t = app_type.lower()
    if t in _EXCLUDED_TYPES:
        return None
    return _TYPE_TO_SECTION.get(t, "games")


def resolve(engine: PolicyEngine, appid: str, app_type: str | None) -> Policy | None:
    """Return the effective policy for (appid, type), or None if excluded."""
    section_name = section_for_type(app_type)
    if section_name is None:
        return None

    base = engine.sections.get(section_name)
    if base is None:
        # Section not declared in TOML -> no active policy.
        base = Policy()

    override = engine.overrides.get(appid, {})
    if override.get("ignore") is True:
        return Policy(
            compat_tool=base.compat_tool,
            launch_options=base.launch_options,
            ignore=True,
        )

    return Policy(
        compat_tool=override.get("compat_tool", base.compat_tool),
        launch_options=override.get("launch_options", base.launch_options),
        ignore=False,
    )
