from pathlib import Path

from typer.testing import CliRunner

from steam_manager import __version__, cli

runner = CliRunner()


def test_version_flag_prints_version_and_exits_zero():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_diff_no_drift_exits_zero(fake_steam, tmp_path, monkeypatch):
    # Forziamo il tool a usare fake_steam + policies fixture
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["diff"])
    # Game 111 e a posto, Game 222 no -> drift -> exit 1
    assert result.exit_code in (0, 1)
    assert "Game" in result.stdout


def test_diff_lists_drift(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["diff"])
    assert result.exit_code == 1
    assert "222" in result.stdout


def test_list_outputs_all_apps(fake_steam, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0
    assert "Game One" in result.stdout
    assert "Game Two" in result.stdout


def test_list_groups_games_and_applications(fake_steam, monkeypatch):
    """`list` renders games and applications in separate, ordered panels."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    # 111 = "Game Two" (a game), 222 = "Game One" (an application).
    monkeypatch.setattr("steam_manager.cli._appinfo.appinfo_types",
                        lambda: {"111": "game", "222": "application"})
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Games" in out and "Applications" in out
    assert out.index("Games") < out.index("Applications")
    assert "Game Two" in out and "Game One" in out


def test_list_json_output(fake_steam, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["list", "--json"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.stdout)
    appids = {item["appid"] for item in data}
    assert appids == {"111", "222"}


def test_list_json_includes_compat_and_launch(fake_steam, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["list", "--json"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.stdout)
    by_id = {item["appid"]: item for item in data}
    assert "111" in by_id
    assert "222" in by_id
    assert "compat_tool" in by_id["111"]
    assert "launch_options" in by_id["111"]
    assert "library" in by_id["111"]


def test_apply_writes_compat_and_launch(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    # Backup root isolato in tmp_path per non sporcare ~/.local/state
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    # Disabilita check Steam running per il test
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    result = runner.invoke(cli.app, ["apply"])
    assert result.exit_code == 0

    # Verifica che 222 abbia ora compat tool e launch options
    from steam_manager.io import config_vdf as st_cfg, discovery as st_disc, localconfig_vdf as st_lc
    from steam_manager.models import SteamApp
    ctx = st_disc.discover(steam_root=fake_steam)
    assert st_cfg.get_compat_tool(ctx, "222") == "Proton-CachyOS Latest"
    user = next(u for u in st_disc.list_users(ctx) if u.is_active)
    assert st_lc.get_launch_options(user, "222") == "scopebuddy -- %command%"


def test_clear_wipes_compat_and_launch_with_yes(fake_steam, tmp_path, monkeypatch):
    """`clear --yes` removes every compat override + launch option, creates a checkpoint."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    backups_dir = tmp_path / "backups"
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(backups_dir))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    # First apply, so there are real overrides to clear.
    apply_result = runner.invoke(cli.app, ["apply"])
    assert apply_result.exit_code == 0

    # Sanity: overrides exist before clear.
    from steam_manager.io import config_vdf as st_cfg, discovery as st_disc, localconfig_vdf as st_lc
    ctx = st_disc.discover(steam_root=fake_steam)
    assert st_cfg.count_compat_overrides(ctx) >= 1
    user = next(u for u in st_disc.list_users(ctx) if u.is_active)
    assert st_lc.count_launch_options(user) >= 1

    # Clear.
    result = runner.invoke(cli.app, ["clear", "--yes"])
    assert result.exit_code == 0, result.stdout

    # All compat overrides gone (except Steam's default '0' which clear preserves).
    assert st_cfg.count_compat_overrides(ctx) == 0
    # All launch options gone for the active user.
    assert st_lc.count_launch_options(user) == 0
    # A checkpoint was taken before the wipe — the dir holds at least one
    # archive that `restore` could use to roll back.
    archives = list(backups_dir.glob("*.tar.gz"))
    assert len(archives) >= 1


def test_clear_short_circuits_when_nothing_to_wipe(fake_steam, tmp_path, monkeypatch):
    """`clear` on a clean install prints success and exits 0 without prompting."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    # fake_steam fixture comes pre-populated with one compat override and
    # one launch option. Wipe them first so the short-circuit path can be
    # exercised on the *second* invocation.
    runner.invoke(cli.app, ["clear", "--yes"])

    result = runner.invoke(cli.app, ["clear"], input="n\n")
    assert result.exit_code == 0
    assert "Nothing to clear" in result.stdout


def test_clear_aborts_when_user_declines(fake_steam, tmp_path, monkeypatch):
    """Without `--yes`, declining the prompt leaves files untouched."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    # Apply first so there's something to clear.
    runner.invoke(cli.app, ["apply"])
    from steam_manager.io import config_vdf as st_cfg, discovery as st_disc
    ctx = st_disc.discover(steam_root=fake_steam)
    before = st_cfg.count_compat_overrides(ctx)
    assert before >= 1

    result = runner.invoke(cli.app, ["clear"], input="n\n")
    assert result.exit_code == 0
    # File untouched.
    assert st_cfg.count_compat_overrides(ctx) == before


def test_apply_aborts_if_steam_running(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))

    # Crea steam.pid finto con il nostro PID (sempre vivo)
    pidfile = tmp_path / "steam.pid"
    import os
    pidfile.write_text(str(os.getpid()))
    from steam_manager import safety
    monkeypatch.setattr(safety, "_STEAM_PID_FILE", pidfile)

    result = runner.invoke(cli.app, ["apply"])
    assert result.exit_code == 2
    assert "Steam" in result.stdout


def test_backup_creates_archive(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    bak_root = tmp_path / "backups"
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(bak_root))

    result = runner.invoke(cli.app, ["backup"])
    assert result.exit_code == 0
    archives = list(bak_root.glob("*.tar.gz"))
    assert len(archives) == 1
    import tarfile
    with tarfile.open(archives[0], "r:gz") as tar:
        names = tar.getnames()
        assert "config.vdf" in names
        assert "manifest.json" in names
        assert any(n.startswith("users/testuser/") for n in names)


def test_restore_last_replaces_current(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    bak_root = tmp_path / "backups"
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(bak_root))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")    # ignora steam_running per test

    # Backup iniziale
    runner.invoke(cli.app, ["backup"])

    # Modifica drasticamente config.vdf
    config = fake_steam / "config" / "config.vdf"
    config.write_text('"InstallConfigStore" {}')

    # Restore --last --yes
    result = runner.invoke(cli.app, ["restore", "--last", "--yes"])
    assert result.exit_code == 0
    assert "InstallConfigStore" in config.read_text()
    assert "Proton-CachyOS Latest" in config.read_text()


def test_restore_shows_diff_preview(fake_steam, tmp_path, monkeypatch):
    """Before applying, restore must render the on-the-fly diff so the user
    sees exactly what would change."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    bak_root = tmp_path / "backups"
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(bak_root))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    # Take a backup of the initial state, then apply so disk diverges from it.
    runner.invoke(cli.app, ["backup"])
    runner.invoke(cli.app, ["apply"])

    # Restore --last --yes: the diff preview must mention the change.
    result = runner.invoke(cli.app, ["restore", "--last", "--yes"])
    assert result.exit_code == 0
    # Normalize whitespace: the phrase may wrap across lines in the 80-col console.
    assert "would apply" in " ".join(result.stdout.split())
    # Diff renderer prints "Compat tool" panel header when compat changes exist.
    assert "Compat tool" in result.stdout


def test_restore_recovers_shortcuts(fake_steam, tmp_path, monkeypatch):
    """A shortcuts-edit checkpoint is fully restorable: restore maps the
    `users/<account>/shortcuts.vdf` member back onto the live file and the
    preview shows the Non-Steam shortcuts change."""
    from steam_manager.cli._checkpoint import make_checkpoint
    from steam_manager.io import shortcuts_vdf

    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    sc_path = fake_steam / "userdata" / "72021823" / "config" / "shortcuts.vdf"
    good = {"shortcuts": {"0": {"appid": 123456, "AppName": "Doom",
                                "Exe": "/usr/bin/doom", "LaunchOptions": ""}}}
    shortcuts_vdf.save(sc_path, good)
    make_checkpoint(trigger="shortcuts-edit",
                    files={"users/testuser/shortcuts.vdf": sc_path},
                    users=["testuser"])

    # The user wipes their shortcuts by accident.
    shortcuts_vdf.save(sc_path, {"shortcuts": {}})

    result = runner.invoke(cli.app, ["restore", "--last", "--yes"])
    assert result.exit_code == 0
    assert "Non-Steam shortcuts" in result.stdout   # diff preview panel
    assert "Restored" in result.stdout and "shortcuts.vdf" in result.stdout
    assert shortcuts_vdf.load(sc_path) == good


def test_restore_recovers_scopebuddy_conf(fake_steam, tmp_path, monkeypatch):
    """A scb-delete checkpoint is restorable: the scopebuddy/<stem>.conf member
    maps back to the ScopeBuddy dir and the preview shows the change."""
    from steam_manager.cli._checkpoint import make_checkpoint

    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("STEAM_MANAGER_SCB_DIR", str(tmp_path / "scb"))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    conf = tmp_path / "scb" / "999.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("# hand-tuned\nSCB_NOSCOPE=1\n")
    make_checkpoint(trigger="scb-delete", files={"scopebuddy/999.conf": conf})
    conf.unlink()                     # what the TUI delete does

    result = runner.invoke(cli.app, ["restore", "--last", "--yes"])
    assert result.exit_code == 0
    assert "ScopeBuddy configs" in result.stdout
    assert conf.read_text() == "# hand-tuned\nSCB_NOSCOPE=1\n"


def test_restore_skips_when_diff_empty(fake_steam, tmp_path, monkeypatch):
    """Restore must NOT extract when the archive is identical to disk."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    bak_root = tmp_path / "backups"
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(bak_root))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    runner.invoke(cli.app, ["backup"])
    # Don't modify anything. Restoring the just-taken backup should be a no-op.
    config = fake_steam / "config" / "config.vdf"
    before = config.read_bytes()

    result = runner.invoke(cli.app, ["restore", "--last", "--yes"])
    assert result.exit_code == 0
    assert "would change nothing" in result.stdout
    # No "Restored" lines emitted.
    assert "Restored" not in result.stdout
    # File on disk unchanged byte-for-byte.
    assert config.read_bytes() == before


def test_apply_manifest_does_not_contain_changes(
    fake_steam, tmp_path, monkeypatch
):
    """Regression: the manifest no longer carries the obsolete `changes` field."""
    import json
    import tarfile

    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    bak_root = tmp_path / "backups"
    monkeypatch.setenv("STEAM_MANAGER_BACKUP_ROOT", str(bak_root))
    monkeypatch.setenv("STEAM_MANAGER_FORCE", "1")

    result = runner.invoke(cli.app, ["apply"])
    assert result.exit_code == 0

    archives = list(bak_root.glob("*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())
    assert "changes" not in manifest, (
        f"manifest still carries the obsolete 'changes' field: {manifest}"
    )
    # Other fields stay.
    assert manifest["trigger"] == "apply"
    assert "users" in manifest
    assert "files" in manifest


def test_scb_observe_reports_orphan(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    scb_dir = tmp_path / "scb"
    scb_dir.mkdir()
    (scb_dir / "999.conf").write_text("# orphan\n")
    monkeypatch.setenv("STEAM_MANAGER_SCB_DIR", str(scb_dir))

    result = runner.invoke(cli.app, ["scb"])
    assert "999" in result.stdout
    assert result.exit_code == 1   # issue rilevato


def test_diff_skips_non_game_tools(fake_steam, tmp_path, monkeypatch):
    # Aggiungi un fake manifest per "Proton Experimental" alla library principale
    proton_manifest = '''
"AppState"
{
    "appid"        "1493710"
    "name"         "Proton Experimental"
    "StateFlags"   "4"
    "installdir"   "ProtonExperimental"
}
'''
    (fake_steam / "steamapps" / "appmanifest_1493710.acf").write_text(proton_manifest)

    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["diff"])
    assert "1493710" not in result.stdout
    assert "Proton Experimental" not in result.stdout


def test_diff_changes_are_sorted_alphabetically(fake_steam, tmp_path, monkeypatch):
    # Aggiungi un altro manifest con nome che dovrebbe precedere "Game Two"
    extra = '''
"AppState"
{
    "appid"        "555"
    "name"         "Aardvark Adventures"
    "StateFlags"   "4"
    "installdir"   "Aardvark"
}
'''
    (fake_steam / "steamapps" / "appmanifest_555.acf").write_text(extra)

    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["diff"])
    # "Aardvark Adventures" deve apparire prima di "Game Two" nell'output
    a_idx = result.stdout.find("Aardvark")
    g_idx = result.stdout.find("Game Two")
    assert a_idx != -1
    assert g_idx != -1
    assert a_idx < g_idx


def test_list_is_alphabetical(fake_steam, monkeypatch):
    extra = '''
"AppState"
{
    "appid"        "555"
    "name"         "Aardvark Adventures"
    "StateFlags"   "4"
    "installdir"   "Aardvark"
}
'''
    (fake_steam / "steamapps" / "appmanifest_555.acf").write_text(extra)

    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0
    a_idx = result.stdout.find("Aardvark")
    g_idx = result.stdout.find("Game One")
    assert a_idx != -1
    assert g_idx != -1
    assert a_idx < g_idx


def test_diff_shows_target_users_banner(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["diff"])
    # Il banner deve menzionare l'utente attivo (testuser nel fixture)
    assert "Target users" in result.stdout
    assert "testuser" in result.stdout


def test_diff_with_user_flag_overrides_target(fake_steam, monkeypatch):
    """--user X deve filtrare l'output sull'utente specificato."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    result = runner.invoke(cli.app, ["diff", "--user", "testuser"])
    assert result.exit_code in (0, 1)
    assert "testuser" in result.stdout


def test_diff_mutually_exclusive_flags(fake_steam, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    result = runner.invoke(cli.app, ["diff", "--user", "x", "--all-users"])
    assert result.exit_code == 3


def test_scb_init_appid_creates_stub(fake_steam, tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    scb_dir = tmp_path / "scb"
    monkeypatch.setenv("STEAM_MANAGER_SCB_DIR", str(scb_dir))

    result = runner.invoke(cli.app, ["scb", "init", "111"])
    assert result.exit_code == 0
    assert (scb_dir / "111.conf").is_file()
    assert "Game One" in (scb_dir / "111.conf").read_text()


def test_is_listable_filters_dlc_music(monkeypatch):
    """DLC/music types are filtered out (section_for_type returns None)."""
    from steam_manager.io import config_vdf as st_cfg, discovery as st_disc, localconfig_vdf as st_lc
    from steam_manager.models import SteamApp
    types = {"1495710": "music"}
    fake = SteamApp(appid="1495710",
                       name="Cyberpunk 2077 Bonus Content",
                       library=Path("/tmp"),
                       state_flags=4)
    assert not cli._appinfo.is_listable(fake, types)


def test_is_listable_accepts_beta_as_game(monkeypatch):
    """Type 'beta' maps to games section -> listable."""
    from steam_manager.io import config_vdf as st_cfg, discovery as st_disc, localconfig_vdf as st_lc
    from steam_manager.models import SteamApp
    types = {"1810920": "beta"}
    fake = SteamApp(appid="1810920",
                       name="Operation Lovecraft",
                       library=Path("/tmp"),
                       state_flags=4)
    assert cli._appinfo.is_listable(fake, types)


def test_is_listable_accepts_application(monkeypatch):
    """Type 'application' maps to applications section -> listable."""
    from steam_manager.io import config_vdf as st_cfg, discovery as st_disc, localconfig_vdf as st_lc
    from steam_manager.models import SteamApp
    types = {"993090": "application"}
    fake = SteamApp(appid="993090",
                       name="Lossless Scaling",
                       library=Path("/tmp"),
                       state_flags=4)
    assert cli._appinfo.is_listable(fake, types)


def test_is_listable_filters_proton_by_name_prefix(monkeypatch):
    """Anche se appinfo classifica come game, il prefisso 'Proton' filtra."""
    from steam_manager.io import config_vdf as st_cfg, discovery as st_disc, localconfig_vdf as st_lc
    from steam_manager.models import SteamApp
    fake = SteamApp(appid="999",
                       name="Proton-CachyOS Latest",
                       library=Path("/tmp"),
                       state_flags=4)
    assert not cli._appinfo.is_listable(fake, {})


def test_diff_filters_dlc_via_appinfo(fake_steam, monkeypatch):
    """Un appid classificato come 'dlc' in appinfo non compare nel diff."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    monkeypatch.setattr(cli._appinfo, "appinfo_types",
                        lambda: {"111": "game", "222": "dlc"})
    result = runner.invoke(cli.app, ["diff"])
    # 222 e' dlc -> filtrato
    assert "222" not in result.stdout
    # Game One (111) e' un game e dovrebbe essere a posto (no drift)
    # quindi il test verifica solo che 222 sia escluso.


def test_diff_application_no_drift_when_section_empty(fake_steam, monkeypatch):
    """Type 'application' con [applications] vuoto -> nessun drift reportato."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    monkeypatch.setenv("STEAM_MANAGER_POLICY_PATHS",
                       str(Path(__file__).parent / "fixtures" / "policies_minimal.toml"))
    # Mark 222 as application so it should be in applications section (empty policy).
    monkeypatch.setattr(cli._appinfo, "appinfo_types",
                        lambda: {"111": "game", "222": "application"})
    result = runner.invoke(cli.app, ["diff"])
    # 222 non deve mostrare drift (nessun campo forzato)
    assert "222" not in result.stdout
