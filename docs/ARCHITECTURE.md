# steam-manager — Architecture & Internals

This document covers the architecture and internals. For what the tool does
and does not do see
the [README](../README.md).

## 1. Overview

The tool never talks to Steam's servers, never launches games, and never
modifies game files or `appmanifest_*.acf`.

## 2. Goals and non-goals

### Goals

- Discover installed games across every registered Steam library folder.
- Read and write the per-app compatibility tool (`config.vdf`).
- Read and write per-user launch options (`localconfig.vdf`).
- Express the desired state declaratively in `policies.toml`, with per
  app-type sections and per-AppID overrides.
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
│       ├── _checkpoint.py           # make_checkpoint() — single manifest schema
│       ├── _steam_guard.py          # check_steam_closed() refuses writes while alive
│       ├── _appinfo.py              # appinfo_types (lru_cache per root) + is_listable filter
│       ├── _update_check.py         # passive newer-release notifier (24h cache, stderr)
│       ├── _targets.py              # --user/--all-users resolution + banner
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
- **`backups.py`** — `create_checkpoint(root, timestamp, files, manifest)`,
  `list_checkpoints(root)`, `extract_checkpoint(archive, targets)`,
  `prune_checkpoints(root, limit)`. Atomic via temp file + rename.

### `cli/` — Typer commands

Shared CLI helpers (private to the cli/ layer):

- **`_rich.py`** — `install_rich_click(app)`: the monkey-patch chain that
  rewires Click to rich-click with aligned `--help` columns. Called by
  `main()` exactly once before dispatch.
- **`_checkpoint.py`** — `make_checkpoint(trigger, files, users,
  max_backups)` + `build_steam_files(ctx, users)`. The single source of
  truth for the checkpoint manifest schema; every destructive command goes
  through here.
- **`_steam_guard.py`** — `check_steam_closed(force)`: exits with
  `STEAM_RUNNING` when Steam is alive and `--force` isn't set.
- **`_update_check.py`** — the passive newer-release notifier: fired from the
  Click result callback, 24h JSON cache, single 2s-timeout GitHub call,
  stderr-only banner; active only in the frozen binary and disabled by
  `STEAM_MANAGER_NO_UPDATE_NOTIFIER`.
- **`_appinfo.py`** — `appinfo_types()` (cached per Steam root through an
  `@lru_cache` helper), `is_listable`, `NON_GAME_NAME_PREFIXES`. The "what
  counts as a game" filter shared by list/diff/apply/scopebuddy.
- **`_targets.py`** — `effective_target_spec`, `resolve_target_users`,
  `target_users_banner`: turn `--user`/`--all-users` flags into a concrete
  user list and a Rich-markup banner.

## 5. Backup format

Each checkpoint is a single `.tar.gz` produced atomically (written to a
`.tmp` file then renamed) and contains:

```text
manifest.json
```

`manifest.json` records:

- `created_at` — ISO-8601 local timestamp (naive, no timezone offset).
- `system` — bool, whether `config.vdf` is in the archive.
- `files` — the archive contents.
