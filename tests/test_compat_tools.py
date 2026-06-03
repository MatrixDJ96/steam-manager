"""Tests for `io/compat_tools.py` — discovery of installed compat tools.

Covers:
- Parsing of `compatibilitytools.d/<name>/compatibilitytool.vdf` (custom)
- Detection of official Proton via appmanifest `name` filter
- Case-insensitive VDF keys
- Sort order (custom first, alphabetical)
- Graceful handling of missing/malformed files
"""
from __future__ import annotations

from pathlib import Path

import pytest

from steam_manager.io import config_vdf, discovery, localconfig_vdf
from steam_manager.io import compat_tools


def _write_custom_tool(steam_root: Path, dir_name: str, tech: str, display: str) -> None:
    """Create a custom tool entry under compatibilitytools.d/."""
    tool_dir = steam_root / "compatibilitytools.d" / dir_name
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "compatibilitytool.vdf").write_text(
        '"compatibilitytools"\n'
        '{\n'
        '    "compat_tools"\n'
        '    {\n'
        f'        "{tech}"\n'
        '        {\n'
        '            "install_path" "."\n'
        f'            "display_name" "{display}"\n'
        '            "from_oslist"  "windows"\n'
        '            "to_oslist"    "linux"\n'
        '        }\n'
        '    }\n'
        '}\n'
    )


def _write_tool_in(base: Path, dir_name: str, tech: str, display: str) -> None:
    """Create a custom tool entry under an arbitrary compatibilitytools.d base."""
    tool_dir = base / dir_name
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "compatibilitytool.vdf").write_text(
        '"compatibilitytools"\n'
        '{\n'
        '    "compat_tools"\n'
        '    {\n'
        f'        "{tech}"\n'
        '        {\n'
        '            "install_path" "."\n'
        f'            "display_name" "{display}"\n'
        '        }\n'
        '    }\n'
        '}\n'
    )


def _write_proton_appmanifest(steam_root: Path, appid: str, name: str, installdir: str) -> None:
    """Add a Proton appmanifest entry to the default library."""
    (steam_root / "steamapps" / f"appmanifest_{appid}.acf").write_text(
        '"AppState"\n'
        '{\n'
        f'    "appid"      "{appid}"\n'
        f'    "name"       "{name}"\n'
        '    "StateFlags" "4"\n'
        f'    "installdir" "{installdir}"\n'
        '}\n'
    )


def test_list_compat_tools_finds_custom(fake_steam: Path):
    _write_custom_tool(fake_steam, "Proton-CachyOS", "Proton-CachyOS_Latest", "Proton CachyOS")
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    custom = [t for t in tools if t.source == "custom"]
    assert len(custom) == 1
    assert custom[0].tech_name == "Proton-CachyOS_Latest"
    assert custom[0].display_name == "Proton CachyOS"
    assert custom[0].install_path == fake_steam / "compatibilitytools.d" / "Proton-CachyOS"


def test_list_compat_tools_finds_official_proton(fake_steam: Path):
    _write_proton_appmanifest(fake_steam, "1493710", "Proton Experimental", "Proton - Experimental")
    _write_proton_appmanifest(fake_steam, "2348590", "Proton 9.0 (Beta)", "Proton 9.0")
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    official_by_tech = {t.tech_name: t for t in tools if t.source == "official"}
    assert "proton_experimental" in official_by_tech
    assert "proton_9" in official_by_tech
    assert official_by_tech["proton_experimental"].display_name == "Proton Experimental"


def test_list_compat_tools_custom_first(fake_steam: Path):
    _write_custom_tool(fake_steam, "GE-Proton", "GE-Proton9", "GE-Proton 9")
    _write_proton_appmanifest(fake_steam, "2348590", "Proton 9.0", "Proton 9.0")
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    sources = [t.source for t in tools]
    # Every custom must come before any official.
    last_custom_idx = max((i for i, s in enumerate(sources) if s == "custom"), default=-1)
    first_official_idx = next((i for i, s in enumerate(sources) if s == "official"), len(sources))
    assert last_custom_idx < first_official_idx


def test_list_compat_tools_finds_system_wide(fake_steam: Path, tmp_path: Path, monkeypatch):
    """Distro-packaged tools (e.g. CachyOS proton-cachyos) live in a system dir."""
    sysdir = tmp_path / "usr_share_steam" / "compatibilitytools.d"
    _write_tool_in(sysdir, "proton-cachyos-slr", "proton-cachyos-slr",
                   "proton-cachyos-11.0 (steam linux runtime)")
    monkeypatch.setenv("STEAM_MANAGER_COMPAT_DIRS", str(sysdir))
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    custom = {t.tech_name: t for t in tools if t.source == "custom"}
    assert "proton-cachyos-slr" in custom
    assert custom["proton-cachyos-slr"].install_path == sysdir / "proton-cachyos-slr"


def test_list_compat_tools_multiple_system_dirs(fake_steam: Path, tmp_path: Path, monkeypatch):
    """STEAM_MANAGER_COMPAT_DIRS is colon-separated; every dir is scanned."""
    d1 = tmp_path / "share" / "compatibilitytools.d"
    d2 = tmp_path / "local_share" / "compatibilitytools.d"
    _write_tool_in(d1, "tool-a", "tool_a", "Tool A")
    _write_tool_in(d2, "tool-b", "tool_b", "Tool B")
    import os
    monkeypatch.setenv("STEAM_MANAGER_COMPAT_DIRS", os.pathsep.join([str(d1), str(d2)]))
    ctx = discovery.discover(steam_root=fake_steam)
    techs = {t.tech_name for t in compat_tools.list_compat_tools(ctx)}
    assert {"tool_a", "tool_b"} <= techs


def test_list_compat_tools_user_shadows_system(fake_steam: Path, tmp_path: Path, monkeypatch):
    """Same tech_name in user + system dir: the user-install entry wins."""
    sysdir = tmp_path / "usr_share_steam" / "compatibilitytools.d"
    _write_tool_in(sysdir, "proton-cachyos-slr", "proton-cachyos-slr", "system build")
    _write_custom_tool(fake_steam, "proton-cachyos-slr", "proton-cachyos-slr", "user build")
    monkeypatch.setenv("STEAM_MANAGER_COMPAT_DIRS", str(sysdir))
    ctx = discovery.discover(steam_root=fake_steam)
    matches = [t for t in compat_tools.list_compat_tools(ctx)
               if t.tech_name == "proton-cachyos-slr"]
    assert len(matches) == 1
    assert matches[0].display_name == "user build"
    assert matches[0].install_path == fake_steam / "compatibilitytools.d" / "proton-cachyos-slr"


def test_list_compat_tools_handles_missing_dir(fake_steam: Path):
    # No compatibilitytools.d at all — should not crash, just no custom entries.
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    assert all(t.source != "custom" for t in tools)


def test_parse_compatibilitytool_vdf_handles_malformed_file(tmp_path: Path):
    bad = tmp_path / "broken.vdf"
    bad.write_text("not valid vdf {{{")
    assert compat_tools.parse_compatibilitytool_vdf(bad) == []


def test_parse_compatibilitytool_vdf_handles_case_variations(tmp_path: Path):
    """Steam's VDF varies capitalization between versions; ci_get() handles both."""
    weird = tmp_path / "weird.vdf"
    weird.write_text(
        '"CompatibilityTools"\n'
        '{\n'
        '    "Compat_Tools"\n'
        '    {\n'
        '        "Proton-Weird" {\n'
        '            "display_name" "Weird Caps Proton"\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    tools = compat_tools.parse_compatibilitytool_vdf(weird)
    assert len(tools) == 1
    assert tools[0].tech_name == "Proton-Weird"
    assert tools[0].display_name == "Weird Caps Proton"


def test_tech_name_for_known_official():
    assert compat_tools._tech_name_for_official("Proton Experimental") == "proton_experimental"
    assert compat_tools._tech_name_for_official("Proton 9.0 (Beta)") == "proton_9"
    assert compat_tools._tech_name_for_official("Proton 8.0") == "proton_8"
    # Unknown name → slugified fallback (best-effort).
    assert compat_tools._tech_name_for_official("Proton Custom Unknown") == "proton_custom_unknown"


def test_list_compat_tools_dedups_official_by_tech_name(fake_steam: Path):
    # Two Proton-9 builds — same tech_name; only one entry should survive.
    _write_proton_appmanifest(fake_steam, "1", "Proton 9.0", "Proton 9.0")
    _write_proton_appmanifest(fake_steam, "2", "Proton 9.0 (Beta)", "Proton 9.0 Beta")
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    tech_names = [t.tech_name for t in tools if t.source == "official"]
    assert tech_names.count("proton_9") == 1


def test_list_compat_tools_filters_steam_linux_runtime(fake_steam: Path):
    """Steam Linux Runtime layers are not usable as a Windows game's compat tool."""
    _write_custom_tool(fake_steam, "LegacyRuntime", "scout_ldlp", "Legacy runtime 1.0")
    _write_custom_tool(fake_steam, "GE-Proton", "GE-Proton9", "Proton-GE Latest")
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    names = {t.display_name for t in tools}
    assert "Legacy runtime 1.0" not in names
    assert "Proton-GE Latest" in names


def test_list_compat_tools_filters_eac_runtime(fake_steam: Path):
    """Proton EasyAntiCheat Runtime is invoked by Proton, not picked by users."""
    _write_proton_appmanifest(fake_steam, "1826330",
                              "Proton EasyAntiCheat Runtime", "Proton EAC Runtime")
    _write_proton_appmanifest(fake_steam, "1493710",
                              "Proton Experimental", "Proton - Experimental")
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx)
    names = {t.display_name for t in tools}
    assert "Proton EasyAntiCheat Runtime" not in names
    assert "Proton Experimental" in names


def test_list_compat_tools_runnable_only_false_returns_all(fake_steam: Path):
    """The debug/diagnostic mode (`runnable_only=False`) returns every entry."""
    _write_custom_tool(fake_steam, "LegacyRuntime", "scout_ldlp", "Legacy runtime 1.0")
    ctx = discovery.discover(steam_root=fake_steam)
    tools = compat_tools.list_compat_tools(ctx, runnable_only=False)
    assert any(t.display_name == "Legacy runtime 1.0" for t in tools)


def test_is_runnable_unit_cases():
    """Boundary cases for the runnable predicate."""
    def t(name: str) -> compat_tools.CompatTool:
        return compat_tools.CompatTool(
            tech_name=name.lower().replace(" ", "_"),
            display_name=name, source="custom", install_path=None,
        )
    assert compat_tools._is_runnable(t("Proton-CachyOS Latest")) is True
    assert compat_tools._is_runnable(t("Proton Experimental")) is True
    assert compat_tools._is_runnable(t("Proton 9.0")) is True
    assert compat_tools._is_runnable(t("Legacy runtime 1.0")) is False
    assert compat_tools._is_runnable(t("Steam Linux Runtime - Soldier")) is False
    assert compat_tools._is_runnable(t("Proton EasyAntiCheat Runtime")) is False
    assert compat_tools._is_runnable(t("Proton BattlEye Runtime")) is False
