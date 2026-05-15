from pathlib import Path

from steam_manager.io import config_vdf, discovery, localconfig_vdf
from steam_manager.models import SteamUser


def test_discover_finds_steam_root_and_libraries(fake_steam: Path):
    ctx = discovery.discover(steam_root=fake_steam)
    assert ctx.root == fake_steam
    assert len(ctx.libraries) == 2
    assert fake_steam in ctx.libraries


def test_steam_discover_captures_library_labels(fake_steam: Path):
    ctx = discovery.discover(steam_root=fake_steam)
    assert "TestLinux" in ctx.library_labels.values()
    assert "TestDisk2" in ctx.library_labels.values()


def test_library_label_helper(fake_steam: Path):
    ctx = discovery.discover(steam_root=fake_steam)
    assert discovery.library_label(ctx, fake_steam) == "TestLinux"


def test_list_users_returns_all_with_active_flag(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    users = discovery.list_users(ctx)
    assert len(users) == 2

    by_name = {u.account_name: u for u in users}
    assert by_name["testuser"].is_active is True
    assert by_name["testuser"].steamid64 == "76561198032287551"
    assert by_name["testuser"].steamid3 == "72021823"   # 76561198032287551 - 76561197960265728
    assert by_name["secondary"].is_active is False


def test_list_apps_enumerates_across_libraries(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    apps = discovery.list_apps(ctx)
    by_id = {a.appid: a for a in apps}
    assert "111" in by_id
    assert "222" in by_id
    assert by_id["111"].name == "Game One"
    assert by_id["222"].name == "Game Two"
    assert by_id["111"].installed is True


def test_list_apps_state_flags_decoded(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    apps = discovery.list_apps(ctx)
    by_id = {a.appid: a for a in apps}
    assert by_id["111"].state_flags == 4
    assert by_id["222"].state_flags == 4


def test_get_compat_tool_existing_appid(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    assert config_vdf.get_compat_tool(ctx, "111") == "Proton-CachyOS Latest"


def test_get_compat_tool_missing_appid(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    assert config_vdf.get_compat_tool(ctx, "999") is None


def test_set_compat_tool_updates_existing(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    config_vdf.set_compat_tool(ctx, "111", "GE-Proton 9-20")
    assert config_vdf.get_compat_tool(ctx, "111") == "GE-Proton 9-20"


def test_set_compat_tool_creates_new_mapping(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    config_vdf.set_compat_tool(ctx, "222", "Proton-CachyOS Latest")
    assert config_vdf.get_compat_tool(ctx, "222") == "Proton-CachyOS Latest"


def test_get_launch_options_existing(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    user = next(u for u in discovery.list_users(ctx) if u.is_active)
    assert localconfig_vdf.get_launch_options(user, "111") == "scopebuddy -- %command%"


def test_get_launch_options_missing(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    user = next(u for u in discovery.list_users(ctx) if u.is_active)
    assert localconfig_vdf.get_launch_options(user, "999") is None


def test_set_launch_options_updates(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    user = next(u for u in discovery.list_users(ctx) if u.is_active)
    localconfig_vdf.set_launch_options(user, "111", "DXVK_FRAME_RATE=0 scopebuddy -- %command%")
    assert localconfig_vdf.get_launch_options(user, "111") == "DXVK_FRAME_RATE=0 scopebuddy -- %command%"


def test_set_launch_options_creates_apps_section_and_entry(fake_steam):
    ctx = discovery.discover(steam_root=fake_steam)
    user = next(u for u in discovery.list_users(ctx) if u.is_active)
    localconfig_vdf.set_launch_options(user, "222", "scopebuddy -- %command%")
    assert localconfig_vdf.get_launch_options(user, "222") == "scopebuddy -- %command%"


def test_get_launch_options_handles_Apps_capital_a(tmp_path):
    """Real Steam uses 'Apps' (capital A) in localconfig.vdf."""
    udir = tmp_path / "userdata" / "12345" / "config"
    udir.mkdir(parents=True)
    (udir / "localconfig.vdf").write_text('''
"UserLocalConfigStore"
{
    "Software"
    {
        "Valve"
        {
            "Steam"
            {
                "Apps"
                {
                    "555"
                    {
                        "LaunchOptions"   "scopebuddy -- %command%"
                    }
                }
            }
        }
    }
}
''')
    user = SteamUser(
        account_name="x", steamid64="76561197960378573",
        steamid3="12345", userdata_dir=tmp_path / "userdata" / "12345",
        is_active=True,
    )
    assert localconfig_vdf.get_launch_options(user, "555") == "scopebuddy -- %command%"
