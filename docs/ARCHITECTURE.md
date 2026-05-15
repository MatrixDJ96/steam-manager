# steam-manager — Architecture & Internals

This document covers the architecture and internals. For what the tool does
and does not do see
the [README](../README.md).

## 1. Overview

`steam-manager` is a command-line tool that brings declarative configuration
to a local Steam install on Linux. It scans every Steam library folder on the
machine, reads the Steam VDF configuration files, and reconciles the current
state with a policy described in `policies.toml`.

The tool never talks to Steam's servers, never launches games, and never
modifies game files or `appmanifest_*.acf`.

## 2. Goals and non-goals

### Goals

- Discover installed games across every registered Steam library folder.
- Read and write the per-app compatibility tool (`config.vdf`).
- Read and write per-user launch options (`localconfig.vdf`).
- Express the desired state declaratively in `policies.toml`, with per
  app-type sections and per-AppID overrides.
- Take an atomic `.tar.gz` checkpoint of the affected files before every
  destructive operation, with an interactive restore command.
- Multi-user aware: operate on the active local account, on all local
  accounts, or on an explicit list.

### Non-goals

- Not a Steam client. Does not launch games, does not authenticate, does not
  talk to Steam's web services.
- Not a Pyroveil manager. Per-game shader/runtime hacks live in
  `~/.pyroveil/` and stay out of scope.
- Does not resolve or validate Proton names. The `compat_tool` value is
  written to Steam verbatim; Steam silently ignores an unrecognized name, so
  policies carry the *tech name* (e.g. `proton-cachyos-slr`).
- Does not write `appmanifest_*.acf`. Those files are parsed only to
  enumerate installed apps.

## 3. Project layout

```text
<repo>/
├── pyproject.toml
├── README.md                        # user-facing quickstart
├── AGENTS.md                        # agent instructions: commands, conventions, gotchas
├── scripts/
│   ├── build.sh                     # PyInstaller --onefile build (emits SHA256)
├── src/steam_manager/
│   ├── __init__.py                  # __version__ (paired with pyproject.toml)
│   ├── __main__.py                  # python -m steam_manager → cli.main()
│   ├── models.py                    # SteamUser, SteamApp, SteamContext, ShortcutsFile, CompatTool
│   ├── policy.py                    # policies.toml merge engine + per-AppID resolve
│   ├── safety.py                    # steam_running() pid-file probe
│   ├── render.py                    # Rich tables, panels, prompts, OSC 8 link helper
│   ├── policies.toml                # factory policy (bundled with package)
│   ├── io/                          # filesystem I/O — no Typer, no Rich
│   │   ├── __init__.py
│   │   ├── _vdf_util.py             # ci_get() — case-insensitive VDF lookups
│   │   ├── discovery.py             # libraryfolders, loginusers, appmanifest_*.acf
│   │   ├── config_vdf.py            # compat-tool R/W on config.vdf
│   │   ├── localconfig_vdf.py       # launch-options R/W on localconfig.vdf
│   │   ├── shortcuts_vdf.py         # binary VDF R/W on shortcuts.vdf
│   │   ├── policies_toml.py         # user policy file R/W (tomlkit-based)
│   │   ├── appinfo.py               # binary appinfo.vdf parser
│   │   ├── scopebuddy.py            # ScopeBuddy observe + stub init
│   │   ├── compat_tools.py          # discovery of installed compat tools (Proton custom + official)
│   │   ├── github_releases.py       # GitHub Releases API discovery (self-update)
│   │   └── backups.py               # atomic .tar.gz checkpoints
│   └── cli/                         # Typer entry + each command in its own file
│       ├── app.py                   # Typer() singleton + root callback
│       ├── _common.py               # ExitCode, path helpers, env-var overrides
│       ├── _rich.py                 # install_rich_click() monkey-patch
│       ├── _editor.py               # choose_editor() used by `shortcuts edit`
│       ├── _checkpoint.py           # make_checkpoint() — single manifest schema
│       ├── _steam_guard.py          # check_steam_closed() refuses writes while alive
│       ├── _appinfo.py              # appinfo_types (lru_cache per root) + is_listable filter
│       ├── _update_check.py         # passive newer-release notifier (24h cache, stderr)
│       ├── _drift.py                # compute_drift() used by list/diff/apply
│       ├── _restore_diff.py         # compute_restore_diff() — archive-vs-live preview
│       ├── _targets.py              # --user/--all-users resolution + banner
│       ├── _wizard_core.py          # pure, render-free config core (Change model, load_state, reducers, apply)
│       ├── _wizard.py               # classic questionary `config --classic` flow (drives _wizard_core)
│       │   ├── app.py               #   ConfigApp on _wizard_core: one-screen editor + async drift
│       ├── _list_render.py          # render_app_groups() — list's Games/Applications panels
│       ├── list_cmd.py              # `list` — game inventory with compat tool + per-user launch options
│       ├── diff_cmd.py              # `diff` — preview policy drift (read-only; exit 1 if drift)
│       ├── apply_cmd.py             # `apply` — write policy drift to disk (auto-backup, no dry-run)
│       ├── clear_cmd.py             # `clear` — wipe all compat overrides + launch options (auto-backup)
│       ├── open_cmd.py              # `open` — open game install dir (or compatdata) via xdg-open
│       ├── backup_cmd.py            # `backup` — manually create a full checkpoint archive
│       ├── restore_cmd.py           # `restore` — interactive restore from a previous checkpoint
│       ├── update_cmd.py            # `update` — self-update binary from GitHub releases
│       ├── config_cmd.py            # `config` sub-typer (get/set/unset/path/wizard); bare/wizard delegate to _config_entry
│       └── shortcuts_cmd.py         # `shortcuts` sub-typer for the binary shortcuts.vdf of non-Steam games (path/show/edit)
├── tests/
│   ├── fixtures/                    # synthetic VDF + TOML fixtures
│   ├── conftest.py                  # fake_steam fixture
└── docs/
    └── ARCHITECTURE.md              # this document
```

External paths used at runtime:

```text
~/.config/steam-manager/policies.toml             # user override
~/.local/state/steam-manager/backups/<ts>.tar.gz  # checkpoint archives
~/.local/state/steam-manager/update_check.json    # update notifier cache
~/.config/scopebuddy/games/steam/<appid>.conf     # ScopeBuddy per-game configs
```

## 4. Module reference

### Core (project root)

- **`models.py`** — `SteamUser`, `SteamApp`, `SteamContext`, `ShortcutsFile`,
  `CompatTool`. Dependency-free dataclasses that cross every layer.
- **`policy.py`** — `Policy`, `PolicyEngine`, `load(paths)`,
  `section_for_type(app_type)`, `resolve(engine, appid, app_type)`. The
  deep-merge engine: `load` reads the TOML files with `tomllib`, the rest is
  pure logic with no project imports.
- **`safety.py`** — `steam_running() -> int | None`. Probes
  `~/.steam/steam.pid`.
- **`render.py`** — Rich-based: `_make_inner_table`, `_panel`,
  `simple_table_str`, `diff_table_str`, `link_cell` (OSC 8), `success`/
  `warning`/`error`/`info`, `menu` / `multiselect` (+ the `BACK` sentinel —
  the uniform back-navigable single- and multi-select used by the wizard; Esc
  yields `BACK`, and `menu` also appends a Back/Exit entry), `dim` (styled
  secondary-text fragment, e.g. a dimmed AppID), `select_one_interactive`,
  `select_apps_interactive`, `effective_max_width`. Uses ANSI named colors
  only, so the terminal theme controls the actual rendering.

### `io/` — filesystem reads/writes

All modules use PyPI `vdf >= 3.4` for text VDF (`io/{discovery,config_vdf,
localconfig_vdf,compat_tools}.py`) and `vdf.binary_load`/`vdf.binary_dump`
for binary VDF (`io/shortcuts_vdf.py`); `io/appinfo.py` parses Steam's
`appinfo.vdf` cache with its own custom binary parser. Case-insensitive
section lookups go through `io/_vdf_util.ci_get()`.

- **`discovery.py`** — `discover(steam_root)`, `list_users(ctx)`,
  `list_apps(ctx)`, `library_label(ctx, path)`. Parses `libraryfolders.vdf`,
  `loginusers.vdf`, `appmanifest_*.acf`.
- **`config_vdf.py`** — `get_compat_tool`, `set_compat_tool`,
  `clear_all_compat`. Writes `~/.local/share/Steam/config/config.vdf`.
- **`localconfig_vdf.py`** — `get_launch_options`, `set_launch_options`,
  `clear_all_launch_options`. Per-user `localconfig.vdf`.
- **`shortcuts_vdf.py`** — `load`, `save`, `validate`, `shortcuts_path`,
  `discover`. Binary VDF for non-Steam shortcuts.
- **`policies_toml.py`** — `user_path`, `load_doc`, `save_doc`,
  `validate_toml`, `get_dotted`/`set_dotted`/`unset_dotted`,
  `render_effective_doc`. `tomlkit`-based to preserve user comments.
- **`appinfo.py`** — `parse(path) -> dict[str, str]`. Custom parser for
  Steam's binary `appinfo.vdf` cache (v29 indexed format + legacy fallback).
  Returns `{}` on parse error so callers can fall back gracefully.
- **`compat_tools.py`** — `list_compat_tools(ctx) -> list[CompatTool]`.
  Discovers Proton/GE-Proton/etc. from two sources: custom tools (one
  `compatibilitytool.vdf` each) found across every `compatibilitytools.d/`
  Steam scans — the per-install `<steam_root>/compatibilitytools.d/` plus the
  system-wide `/usr/share/steam` and `/usr/local/share/steam` dirs where
  distro packages land (Arch/CachyOS `proton-cachyos`), with the per-install
  root shadowing same-named system entries — and `appmanifest_*.acf` filtered
  by `name.startswith("Proton")` (official Proton builds Steam installs as
  apps). The system dirs are overridable via `STEAM_MANAGER_COMPAT_DIRS`. Used
  by the `config wizard` picker so the user never types a tech_name by hand.
- **`github_releases.py`** — GitHub Releases API discovery for self-update:
  stdlib `urllib.request` + `json` only, returns plain dataclasses for the
  CLI layer to render. Used by `update` and the passive update notifier.
- **`backups.py`** — `create_checkpoint(root, timestamp, files, manifest)`,
  `list_checkpoints(root)`, `extract_checkpoint(archive, targets)`,
  `prune_checkpoints(root, limit)`. Atomic via temp file + rename.

### `cli/` — Typer commands

Shared CLI helpers (private to the cli/ layer):

- **`_common.py`** — `ExitCode`, `USER_POLICY_PATH`, `steam_root()`,
  `discover_steam()`, `policy_paths()`, `backup_root()`, `scb_dir()`,
  `config_ui_mode()`, `scb_ui_mode()`, `iso_timestamp()`,
  `update_state_path()`. Honors the `STEAM_MANAGER_*` env-var overrides used
  by tests. `discover_steam()` is how every command that reads Steam, except
  `config`, finds it: a missing root prints one error line and exits 3.
- **`_rich.py`** — `install_rich_click(app)`: the monkey-patch chain that
  rewires Click to rich-click with aligned `--help` columns. Called by
  `main()` exactly once before dispatch.
- **`_editor.py`** — `choose_editor()`: `$EDITOR` → `vi`/`nano`/`nvim`.
- **`_checkpoint.py`** — `make_checkpoint(trigger, files, users,
  max_backups)` + `build_steam_files(ctx, users)`. The single source of
  truth for the checkpoint manifest schema; every destructive command goes
  through here.
- **`_restore_diff.py`** — `compute_restore_diff(archive_path, ctx, users,
  users_in_archive)`. Extracts the archive into a tempdir and returns a
  change list compatible with `render.diff_table_str`. Used by `restore`
  to show a preview before extracting.
- **`_steam_guard.py`** — `check_steam_closed(force)`: exits with
  `STEAM_RUNNING` when Steam is alive and `--force` isn't set.
- **`_update_check.py`** — the passive newer-release notifier: fired from the
  Click result callback, 24h JSON cache, single 2s-timeout GitHub call,
  stderr-only banner; active only in the frozen binary and disabled by
  `STEAM_MANAGER_NO_UPDATE_NOTIFIER`.
- **`_appinfo.py`** — `appinfo_types()` (cached per Steam root through an
  `@lru_cache` helper), `is_listable`, `NON_GAME_NAME_PREFIXES`. The "what
  counts as a game" filter shared by list/diff/apply/scopebuddy.
- **`_drift.py`** — `compute_drift(ctx, apps, users, engine, target_spec)`:
  the diff between on-disk state and resolved policy. Used by `list` (to
  mark drifting rows bold), `diff` (read-only preview), and `apply` (which
  writes the drift away).
- **`_targets.py`** — `effective_target_spec`, `resolve_target_users`,
  `target_users_banner`: turn `--user`/`--all-users` flags into a concrete
  user list and a Rich-markup banner.
- **`_list_render.py`** — `render_app_groups(console, ctx, listable, types,
  target_users, drift_appids)`: the Games/Applications panels `list` prints.
  Keeps `list_cmd` a thin orchestrator; grouping mirrors
  `policy.section_for_type`.

The `config` editor is a **shared pure core with two front-ends**:

- **`_wizard.py`** — the classic questionary flow (`--classic`), also driving
  `_wizard_core`.

## 5. Backup format

Each checkpoint is a single `.tar.gz` produced atomically (written to a
`.tmp` file then renamed) and contains:

```text
manifest.json
config.vdf                            # system-wide compat config (apply/clear/manual)
users/<account>/localconfig.vdf       # one per affected user (apply/clear/manual)
users/<account>/shortcuts.vdf         # shortcuts-edit
```

`manifest.json` records:

- `created_at` — ISO-8601 local timestamp (naive, no timezone offset).
- `system` — bool, whether `config.vdf` is in the archive.
- `users` — list of account names whose `localconfig.vdf` or
  `shortcuts.vdf` is in the archive.
- `files` — the archive contents.

The schema is intentionally minimal: it stores no drift snapshot, because
the restore preview is computed on the fly by extracting the archive into a
tempdir and diffing against the live state. `restore` ignores any other
manifest field, a `changes` list included.

Restore flow (in `cli/restore_cmd.py`):

1. Pick a checkpoint (`--last` or interactive single-select).
2. Compute a preview via `cli/_restore_diff.compute_restore_diff()`:
   extract the archive into a `tempfile.TemporaryDirectory`, parse each
   Steam file with the by-path readers in `io/config_vdf.py`,
   `io/localconfig_vdf.py` and `io/shortcuts_vdf.py`, compare ScopeBuddy
   configs byte for byte, and diff each against the live state.
3. If the diff is empty — the archive is identical to disk — print
   `would change nothing — already in this state.` and exit OK without
   extracting.
4. Otherwise render the diff with `render.diff_table_str()` (same renderer
   as the `diff` command), prompt for confirmation unless `--yes`, then
   extract for real.
