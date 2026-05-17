# steam-manager — Architecture & Internals

This document covers the architecture, module APIs, backup format, build
pipeline, and testing approach. For end-user installation and commands see
the [README](../README.md); for common scenarios see
[`docs/HOWTO.md`](HOWTO.md); for the full configuration schema, exit codes,
and operator reference see [`docs/REFERENCE.md`](REFERENCE.md).

## 1. Overview

`steam-manager` is a command-line tool that brings declarative configuration
to a local Steam install on Linux. It scans every Steam library folder on the
machine, reads the Steam VDF configuration files, and reconciles the current
state with a policy described in `policies.toml`.

The tool is read/write on Steam's local configuration only. It never talks to
Steam's servers, never launches games, and never modifies game files or
`appmanifest_*.acf`.

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
- ScopeBuddy integration: passively observe whether per-game stubs exist for
  games that opt into `scopebuddy` via launch options, and generate stubs on
  demand.

### Non-goals

- Not a Steam client. Does not launch games, does not authenticate, does not
  talk to Steam's web services.
- Not a Pyroveil manager. Per-game shader/runtime hacks live in
  `~/.pyroveil/` and stay out of scope.
- Does not resolve abstract Proton names. A value like
  `"Proton-CachyOS Latest"` is written to Steam verbatim; Steam resolves it.
- Does not write `appmanifest_*.acf`. Those files are parsed only to
  enumerate installed apps.

## 3. Project layout

The source tree is layered into `cli/` (Typer commands) and `io/` (filesystem
reads/writes), with a thin core of `policy.py`/`safety.py`/`render.py`/
`models.py` between them. Dependency direction is strictly downward — `cli/`
imports from `io/`, never the reverse. `tests/test_architecture.py` enforces
this with AST inspection.

```
<repo>/
├── pyproject.toml
├── README.md                        # user-facing quickstart
├── CLAUDE.md                        # contributor + Claude playbook
├── scripts/
│   ├── build.sh                     # PyInstaller --onefile build (emits SHA256)
│   └── install.sh                   # one-line installer with version pin + SHA256 verify
├── src/steam_manager/
│   ├── __init__.py                  # __version__ (paired with pyproject.toml)
│   ├── __main__.py                  # python -m steam_manager → cli.main()
│   ├── models.py                    # SteamUser, SteamApp, SteamContext, ShortcutsFile
│   ├── policy.py                    # policies.toml merge engine + per-AppID resolve
│   ├── safety.py                    # steam_running() pid-file probe (+ io.backups shim)
│   ├── render.py                    # Rich tables, panels, prompts, OSC 8 link helper
│   ├── steam.py                     # backward-compat shim → io/{discovery,config_vdf,...}
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
│   │   └── backups.py               # atomic .tar.gz checkpoints
│   └── cli/                         # Typer entry + each command in its own file
│       ├── __init__.py              # wires side-effect imports + main()
│       ├── app.py                   # Typer() singleton + root callback
│       ├── _common.py               # ExitCode, path helpers, env-var overrides
│       ├── _rich.py                 # install_rich_click() monkey-patch
│       ├── _editor.py               # choose_editor() shared by config + shortcuts
│       ├── _checkpoint.py           # make_checkpoint() — single manifest schema
│       ├── _steam_guard.py          # check_steam_closed() refuses writes while alive
│       ├── _appinfo.py              # appinfo_types @lru_cache + is_listable filter
│       ├── _drift.py                # compute_drift() used by list/diff/apply
│       ├── _targets.py              # --user/--all-users resolution + banner
│       ├── list_cmd.py              # `list` — game inventory with compat tool + per-user launch options
│       ├── diff_cmd.py              # `diff` — preview policy drift (read-only; exit 1 if drift)
│       ├── apply_cmd.py             # `apply` — write policy drift to disk (auto-backup, no dry-run)
│       ├── clear_cmd.py             # `clear` — wipe all compat overrides + launch options (auto-backup)
│       ├── open_cmd.py              # `open` — open game install dir (or compatdata) via xdg-open
│       ├── backup_cmd.py            # `backup` — manually create a full checkpoint archive
│       ├── restore_cmd.py           # `restore` — interactive restore from a previous checkpoint
│       ├── update_cmd.py            # `update` — self-update binary from GitHub releases
│       ├── config_cmd.py            # `config` sub-typer for ~/.config/steam-manager/policies.toml (path/show/edit/get/set/...)
│       ├── scopebuddy_cmd.py        # `scopebuddy` sub-typer for per-game ScopeBuddy stubs (observe/init)
│       └── shortcuts_cmd.py         # `shortcuts` sub-typer for the binary shortcuts.vdf of non-Steam games (path/show/edit)
├── tests/
│   ├── fixtures/                    # synthetic VDF + TOML fixtures
│   ├── conftest.py                  # fake_steam fixture
│   ├── test_architecture.py         # AST-based layering invariants
│   └── test_*.py                    # 113 tests total
└── docs/
    ├── HOWTO.md                     # cookbook for common scenarios
    ├── REFERENCE.md                 # operator reference (schema, exit codes, env vars)
    └── ARCHITECTURE.md              # this document
```

External paths used at runtime:

```
~/.config/steam-manager/policies.toml             # user override (XDG_CONFIG_HOME)
~/.local/state/steam-manager/backups/<ts>.tar.gz  # checkpoint archives (XDG_STATE_HOME)
```

## 4. Module reference

### Core (project root)

- **`models.py`** — `SteamUser`, `SteamApp`, `SteamContext`, `ShortcutsFile`.
  Dependency-free dataclasses that cross every layer.
- **`policy.py`** — `Policy`, `PolicyEngine`, `load(paths)`,
  `section_for_type(app_type)`, `resolve(engine, appid, app_type)`. The
  deep-merge engine; pure logic over `models`, no file I/O.
- **`safety.py`** — `steam_running() -> int | None`. Probes
  `~/.steam/steam.pid`. Also re-exports `io.backups.{create,list,extract,
  prune}_checkpoint` so legacy callers see the old API surface.
- **`render.py`** — Rich-based: `_make_inner_table`, `_panel`,
  `simple_table_str`, `diff_table_str`, `link_cell` (OSC 8), `success`/
  `warning`/`error`/`info`, `select_one_interactive`,
  `select_apps_interactive`, `effective_max_width`. Uses ANSI named colors
  only, so the terminal theme controls the actual rendering.
- **`steam.py`** — backward-compat shim re-exporting the io/ surface
  (`from steam_manager import steam; steam.discover(); steam.get_compat_tool()`
  still work). Deprecated; new code should import from `io/` directly.

### `io/` — filesystem reads/writes

All modules use PyPI `vdf >= 3.4` for text VDF (`io/{discovery,config_vdf,
localconfig_vdf}.py`) and `vdf.binary_load`/`vdf.binary_dump` for binary VDF
(`io/{shortcuts_vdf,appinfo}.py`). Case-insensitive section lookups go
through `io/_vdf_util.ci_get()`.

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
  `render_initial_template`, `validate_toml`. `tomlkit`-based to preserve
  user comments.
- **`appinfo.py`** — `parse(path) -> dict[str, str]`. Custom parser for
  Steam's binary `appinfo.vdf` cache (v29 indexed format + legacy fallback).
  Returns `{}` on parse error so callers can fall back gracefully.
- **`scopebuddy.py`** — `observe(configs_dir, installed_appids,
  launch_options)` returns a `ScopeBuddyObservation` with
  `games_with_scb_launch` / `missing_configs` / `orphan_configs`.
  `init_stub(target_path, name, force)` writes a minimal two-line stub.
- **`backups.py`** — `create_checkpoint(root, ts, files, manifest)`,
  `list_checkpoints(root)`, `extract_checkpoint(archive, targets)`,
  `prune_checkpoints(root, limit)`. Atomic via temp file + rename.

### `cli/` — Typer commands

Each top-level command (`list`, `diff`, `apply`, `clear`, `open`, `backup`,
`restore`) lives in its own `<verb>_cmd.py`. Each sub-typer family (`config`,
`scopebuddy`, `shortcuts`) lives in `<name>_cmd.py`. The Typer app singleton is in
`cli/app.py`; everything is wired in `cli/__init__.py` via side-effect
imports.

Shared CLI helpers (private to the cli/ layer):

- **`_common.py`** — `ExitCode`, `USER_POLICY_PATH`, `steam_root()`,
  `policy_paths()`, `backup_root()`, `iso_timestamp()`. Honors the
  `STEAM_MANAGER_*` env-var overrides used by tests.
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
- **`_appinfo.py`** — `appinfo_types()` with `@lru_cache`, `is_listable`,
  `NON_GAME_NAME_PREFIXES`. The "what counts as a game" filter shared by
  list/diff/apply/scopebuddy.
- **`_drift.py`** — `compute_drift(ctx, apps, users, engine, target_spec)`:
  the diff between on-disk state and resolved policy. Used by `list` (to
  mark drifting rows bold), `diff` (read-only preview), and `apply` (which
  writes the drift away).
- **`_targets.py`** — `effective_target_spec`, `resolve_target_users`,
  `target_users_banner`: turn `--user`/`--all-users` flags into a concrete
  user list and a Rich-markup banner.

## 5. Backup format

Each checkpoint is a single `.tar.gz` produced atomically (written to a
`.tmp` file then renamed) and contains:

```
manifest.json
config.vdf                            # system-wide compat config
users/<account>/localconfig.vdf       # one per affected user
```

`manifest.json` records:

- `created_at` — ISO-8601 with timezone.
- `trigger` — `manual`, `apply`, `clear`, or `shortcuts-edit`.
- `system` — bool, whether `config.vdf` is in the archive.
- `users` — list of account names with `localconfig.vdf` in the archive.
- `files` — the archive contents.

The schema is intentionally minimal. An earlier version stored a `changes`
list (drift snapshot at apply time) but `restore` never consumed it — the
restore preview is computed on the fly by extracting the archive into a
tempdir and diffing against the live state. Old archives still carrying
the field are silently ignored.

Restore flow (in `cli/restore_cmd.py`):

1. Pick a checkpoint (`--last` or interactive single-select).
2. Compute a preview via `cli/_restore_diff.compute_restore_diff()`:
   extract the archive into a `tempfile.TemporaryDirectory`, parse each
   file with the by-path readers in `io/config_vdf.py` and
   `io/localconfig_vdf.py`, diff each AppID against the live state.
3. If the diff is empty — the archive is identical to disk — print
   `would change nothing — already in this state.` and exit OK without
   extracting.
4. Otherwise render the diff with `render.diff_table_str()` (same renderer
   as the `diff` command), prompt for confirmation unless `--yes`, then
   extract for real.

The archive layout, retention policy (`[general] max_backups`), and the user
restore flow are documented in [`docs/REFERENCE.md`](REFERENCE.md#backups).

## 6. Build pipeline

`scripts/build.sh` produces `dist/steam-manager` — a single-file standalone
Linux x86_64 binary (~16 MB) via PyInstaller `--onefile`. The binary bundles
the Python runtime and every dependency, including the factory
`policies.toml` and the parsed-at-runtime `appinfo.vdf`. It requires no
Python or pip on the target system, only glibc.

`scripts/install.sh` is the one-line installer published at
`raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh`.
It downloads the latest GitHub release asset into `~/.local/bin/` (override
with `STEAM_MANAGER_INSTALL_DIR`), runs a smoke test (`--help`), and warns
if the install dir is not on `PATH`.

`scripts/release.sh` is the publisher. It reads release notes from
`--notes-file` (or stdin), appends a `## Install` section pinned to the tag
(`STEAM_MANAGER_VERSION=vX.Y.Z bash`), and calls `gh release create` with
the binary + `.sha256` attached. The pinned section exists so that
copy-pasting the install command from an older release page installs *that*
release, not whatever `latest` resolves to weeks later. The script refuses
if the supplied notes already contain an `## Install` heading — it owns
that section.

## 7. Testing

113 tests under `tests/`, all driven by `pytest` with synthetic VDF and TOML
fixtures, running in under one second. The `fake_steam` fixture in
`conftest.py` builds a self-contained Steam tree in `tmp_path` so tests
never touch the real Steam install.

Tests that need to bypass production paths set env vars honored by
`cli/_common.py`:

- `STEAM_MANAGER_STEAM_ROOT` — overrides the discovered Steam root.
- `STEAM_MANAGER_POLICY_PATHS` — colon-separated list of TOML paths.
- `STEAM_MANAGER_BACKUP_ROOT` — overrides the backup directory.
- `STEAM_MANAGER_USER_POLICY` — overrides the user policy file path.
- `STEAM_MANAGER_SCB_DIR` — overrides the ScopeBuddy configs dir.
- `STEAM_MANAGER_FORCE=1` — equivalent to passing `--force`.

Commands are exercised through `typer.testing.CliRunner` against `cli.app`.
Rich output goes to a `StringIO` in tests, which strips ANSI; substring
assertions on table content work, but assertions on colors/styles do not.

### Architectural tests

`tests/test_architecture.py` uses AST inspection to enforce the dependency
rules listed in section 3. The five rules tested:

- `io/*.py` may not import from `cli/`, `render`, `policy`, `safety`
- `policy.py` may not import from `cli/`, `io/`, `render`
- `render.py` must not import any project module (only `models`, optional)
- `safety.py` may not import from `cli/`, `render`, `policy`
- `models.py` must not import any project module

A future refactor that accidentally introduces a layer-crossing import
(e.g. `io/scopebuddy.py` reaching for `render.error` "for convenience")
fails this test before any functional test runs — a much cleaner signal
than chasing the resulting runtime error.
