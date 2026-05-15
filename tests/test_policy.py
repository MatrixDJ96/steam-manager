from pathlib import Path

import pytest

from steam_manager import policy

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_single_file():
    engine = policy.load([FIXTURES / "policies_minimal.toml"])
    assert engine.target_users == ["active"]
    assert engine.max_backups == 20
    assert engine.sections["games"].compat_tool == "Proton-CachyOS Latest"
    assert engine.sections["games"].launch_options == "scopebuddy -- %command%"
    # applications section is empty
    assert "applications" in engine.sections
    assert engine.sections["applications"].compat_tool is None


def test_load_two_files_deep_merge():
    engine = policy.load([
        FIXTURES / "policies_minimal.toml",
        FIXTURES / "policies_override.toml",
    ])
    assert engine.max_backups == 50
    assert engine.sections["games"].compat_tool == "Proton-CachyOS Latest"
    assert "1495710" in engine.overrides
    assert "2183900" in engine.overrides


def test_target_users_list_replaces_not_appends(tmp_path):
    base = tmp_path / "base.toml"
    base.write_text('[general]\ntarget_users = ["active"]\n')
    over = tmp_path / "over.toml"
    over.write_text('[general]\ntarget_users = ["specific"]\n')
    engine = policy.load([base, over])
    assert engine.target_users == ["specific"]


def test_load_missing_file_silently_skipped(tmp_path):
    engine = policy.load([
        FIXTURES / "policies_minimal.toml",
        tmp_path / "does-not-exist.toml",
    ])
    assert engine.sections["games"].compat_tool == "Proton-CachyOS Latest"


def test_load_invalid_max_backups_raises(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[general]\nmax_backups = "twenty"\n')
    with pytest.raises(ValueError, match="max_backups"):
        policy.load([FIXTURES / "policies_minimal.toml", bad])


def test_resolve_game_uses_games_section():
    engine = policy.load([FIXTURES / "policies_minimal.toml"])
    p = policy.resolve(engine, "111", "game")
    assert p is not None
    assert p.compat_tool == "Proton-CachyOS Latest"
    assert p.launch_options == "scopebuddy -- %command%"
    assert p.ignore is False


def test_resolve_beta_uses_games_section():
    engine = policy.load([FIXTURES / "policies_minimal.toml"])
    p = policy.resolve(engine, "111", "beta")
    assert p is not None
    assert p.compat_tool == "Proton-CachyOS Latest"


def test_resolve_application_no_compat_or_launch():
    engine = policy.load([FIXTURES / "policies_minimal.toml"])
    p = policy.resolve(engine, "993090", "application")
    assert p is not None
    assert p.compat_tool is None        # niente policy per applications
    assert p.launch_options is None


def test_resolve_dlc_returns_none():
    engine = policy.load([FIXTURES / "policies_minimal.toml"])
    assert policy.resolve(engine, "1495710", "music") is None
    assert policy.resolve(engine, "999", "dlc") is None


def test_resolve_unknown_type_fallbacks_to_games():
    engine = policy.load([FIXTURES / "policies_minimal.toml"])
    p = policy.resolve(engine, "111", None)
    assert p is not None
    assert p.compat_tool == "Proton-CachyOS Latest"


def test_resolve_override_takes_precedence():
    engine = policy.load([
        FIXTURES / "policies_minimal.toml",
        FIXTURES / "policies_override.toml",
    ])
    p = policy.resolve(engine, "2183900", "game")
    assert p.launch_options == "DXVK_FRAME_RATE=0 scopebuddy -- %command%"
    assert p.compat_tool == "Proton-CachyOS Latest"   # da [games]


def test_resolve_ignore_override():
    engine = policy.load([FIXTURES / "policies_minimal.toml"])
    p = policy.resolve(engine, "1495710", "game")    # ignore=true in TOML
    assert p.ignore is True


def test_section_for_type():
    assert policy.section_for_type("game") == "games"
    assert policy.section_for_type("beta") == "games"
    assert policy.section_for_type("application") == "applications"
    assert policy.section_for_type("dlc") is None
    assert policy.section_for_type("music") is None
    assert policy.section_for_type("tool") is None
    assert policy.section_for_type(None) == "games"   # fallback
