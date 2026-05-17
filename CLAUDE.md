# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup quirk

The repo lives on an NTFS partition. Python's `site-packages` performs poorly there, so the venv is on btrfs and symlinked into the repo:

```bash
python3 -m venv ~/.venvs/steam-manager      # only if not already present
ln -sf ~/.venvs/steam-manager .venv         # idempotent
source .venv/bin/activate
pip install -e ".[dev]"                     # add [build] for PyInstaller
```

`.venv` is a symlink — anything that resolves real paths through it will land in `~/.venvs/steam-manager/`.

## Common commands

```bash
pytest                                      # full suite (223 tests, <2s)
pytest tests/test_cli.py -v                 # one file
pytest tests/test_architecture.py           # layering invariants (5 tests)
pytest -k "diff and appid"                  # one test by name pattern
pytest --cov                                # opt-in coverage (uses pyproject config)

steam-manager --help                        # runs from editable install
steam-manager --version                     # also a fast sanity check that the install resolves
python -m steam_manager --help              # equivalent

./scripts/build.sh                          # PyInstaller --onefile → dist/steam-manager (~16 MB) + dist/steam-manager.sha256
```

There is no linter or formatter wired into the project. New code should follow the existing style (4-space indent, `from __future__ import annotations`, ANSI-named colors only in `render.py`).

## Architecture

The package is split into three layers — `cli/` (Typer commands), `io/` (filesystem reads/writes), and a thin core of `policy.py`/`safety.py`/`render.py`/`models.py`. Dependency direction is **strictly downward**: `cli/` imports from `io/`, never the reverse. `tests/test_architecture.py` enforces this with AST inspection — if you break the layering, that test fails first.

```
src/steam_manager/
├── __init__.py           __version__ (single source of truth, paired with pyproject.toml)
├── models.py             SteamUser, SteamApp, SteamContext, ShortcutsFile (shared dataclasses)
├── policy.py             policies.toml merge engine + per-AppID resolve
├── safety.py             steam_running() — pid-file probe + io.backups re-exports
├── render.py             Rich tables/panels/prompts, OSC 8 link helper
├── steam.py              backward-compat shim re-exporting io.{discovery,config_vdf,localconfig_vdf}
│
├── io/                   filesystem I/O — zero Typer, zero Rich
│   ├── discovery.py      libraryfolders.vdf, loginusers.vdf, appmanifest_*.acf
│   ├── config_vdf.py     compat tool R/W on config.vdf
│   ├── localconfig_vdf.py launch options R/W on per-user localconfig.vdf
│   ├── shortcuts_vdf.py  binary VDF R/W on shortcuts.vdf (non-Steam games)
│   ├── policies_toml.py  user policy file R/W (tomlkit-based, preserves comments)
│   ├── backups.py        atomic .tar.gz checkpoint API (create/list/extract/prune)
│   ├── appinfo.py        parser for Steam's binary appinfo.vdf cache
│   ├── scopebuddy.py     observe missing/orphan configs, init L1 stub
│   ├── compat_tools.py   discovery of installed compat tools (Proton custom + official)
│   └── _vdf_util.py      private: ci_get() for case-insensitive VDF lookups
│
└── cli/                  Typer + rich-click layer
    ├── app.py            `app = typer.Typer(...)`, version callback, root callback
    ├── _common.py        ExitCode, USER_POLICY_PATH, steam_root, backup_root, iso_timestamp
    ├── _rich.py          install_rich_click() — Click monkey-patch for aligned --help columns
    ├── _editor.py        choose_editor() used by `shortcuts edit`
    ├── _checkpoint.py    make_checkpoint() + build_steam_files() — single manifest schema
    ├── _steam_guard.py   check_steam_closed() — refuses writes while Steam is alive
    ├── _appinfo.py       appinfo_types @lru_cache + is_listable() + NON_GAME_NAME_PREFIXES
    ├── _drift.py         compute_drift() — used by list/diff/apply
    ├── _targets.py       resolve_target_users/effective_target_spec/target_users_banner
    ├── _wizard.py        `config wizard` flow (show + targeted edit + diff + confirm)
    ├── list_cmd.py       `list` — game inventory with compat tool + per-user launch options
    ├── diff_cmd.py       `diff` — preview policy drift (read-only; exit 1 if drift)
    ├── apply_cmd.py      `apply` — write policy drift to disk (auto-backup, no dry-run)
    ├── clear_cmd.py      `clear` — wipe all compat overrides + launch options (auto-backup)
    ├── open_cmd.py       `open` — open game install dir (or compatdata) via xdg-open
    ├── backup_cmd.py     `backup` — manually create a full checkpoint archive
    ├── restore_cmd.py    `restore` — interactive restore from a previous checkpoint
    ├── update_cmd.py     `update` — self-update binary from GitHub releases
    ├── config_cmd.py     `config` sub-typer for ~/.config/steam-manager/policies.toml (path/show/edit/get/set/...)
    ├── scopebuddy_cmd.py `scopebuddy` sub-typer for per-game ScopeBuddy stubs (observe/init)
    ├── shortcuts_cmd.py  `shortcuts` sub-typer for the binary shortcuts.vdf of non-Steam games (path/show/edit)
    └── __init__.py       wires everything: side-effect imports of *_cmd, add_typer, main()
```

Layer rules (tested by `tests/test_architecture.py`):
- `io/*.py` must not import from `cli/`, `render`, `policy`, `safety`
- `policy.py` must not import from `cli/`, `io/`, `render`
- `render.py` must not import any project module
- `safety.py` must not import from `cli/`, `render`, `policy`
- `models.py` must not import any project module

Sibling helpers in `cli/_*.py` may import each other freely; only the layer boundaries above are enforced.

`cli/config_cmd.py` uses `tomlkit` (not stdlib `tomllib`) because writes must preserve user comments. The PyInstaller build hidden-imports it; if you add modules with similar non-trivial import requirements, declare them in `scripts/build.sh`.

### Doc layout (Diátaxis)

- `README.md` — quickstart, demo, what-it-is/isn't. User-first.
- `docs/HOWTO.md` — task-oriented recipes ("how to apply a policy across users").
- `docs/REFERENCE.md` — exhaustive schema, exit codes, env vars, terminal compat.
- `docs/ARCHITECTURE.md` — module reference, backup format internals, build pipeline.
- `CLAUDE.md` — this file: contributor + Claude playbook for repo quirks.

When adding content, match the audience to the file. Internal API details belong in `ARCHITECTURE`; user-visible flags belong in `REFERENCE`; one-liner walkthroughs belong in `HOWTO`.

### rich-click integration (cli/_rich.py)

The CLI surrenders Typer's help formatter to rich-click for uniform column alignment across the Options and Commands panels. `Typer(rich_markup_mode=None)` disables Typer's own rich rendering; `cli/_rich.install_rich_click(app)` then re-classes the generated Click command tree to rich-click's `RichGroup`/`RichCommand` and monkey-patches `RichOptionPanel.get_table` / `RichCommandPanel.get_table` to force a fixed first-column width. `main()` in `cli/__init__.py` calls this once before dispatch. Don't try to "clean up" by moving back to plain Typer — uniform `--help` column alignment depends on it.

### Configuration layering

`policies.toml` is bundled inside the package at `src/steam_manager/policies.toml` (loaded via `importlib.resources.files()` so it works in editable installs, wheels, and the PyInstaller `_MEIPASS` bundle equally). User overrides live in `~/.config/steam-manager/policies.toml` and are deep-merged on top. See `docs/REFERENCE.md` for the full `[general]/[games]/[applications]/[overrides.<appid>]` schema and `docs/ARCHITECTURE.md` for the internal layering.

### App-type filtering

The list of "what counts as a game" is decided by parsing Steam's binary `appinfo.vdf` cache (`~/.local/share/Steam/appcache/appinfo.vdf`) for each app's `common.type`. `policy.section_for_type()` maps that type to a policy section name (or `None` to filter the app out entirely). A name-prefix fallback in `cli._appinfo.NON_GAME_NAME_PREFIXES` covers cases where the cache is missing or misclassifies. If you find yourself adding ad-hoc filters to `cli._drift.compute_drift`, the right place is almost certainly `policy.section_for_type` or `io.appinfo.parse`.

### Backups are archives, not directories

Every destructive operation (`apply`, `clear`, `backup`, `shortcuts edit`) calls `cli._checkpoint.make_checkpoint()`, which builds the standardized manifest and delegates to `io.backups.create_checkpoint()`. The result is a single `<timestamp>.tar.gz` in `~/.local/state/steam-manager/backups/` containing `manifest.json` plus the snapshotted files. Atomic via temp file + rename. Adding a new trigger (e.g. for a future `shortcuts restore` command) is a one-line change in `make_checkpoint()` — don't open-code a new manifest pattern.

The manifest schema is intentionally minimal: `created_at`, `trigger`, `system` (bool), `users` (list of account names), `files` (archive members). It does NOT store the drift list anymore — that turned out to be unused dead weight, because `restore` always computes a fresh diff on the fly (`cli/_restore_diff.compute_restore_diff()`) by extracting the archive into a tempdir and comparing it against the live state. The preview is rendered with the same `render.diff_table_str()` that `diff` uses, so the visual is consistent across both commands.

### VDF case-insensitivity

Real Steam writes keys inconsistently between versions: the apps section in `localconfig.vdf` is `"Apps"` on some installs and `"apps"` on others; same for the intermediate path segments. `io/_vdf_util.ci_get()` and the explicit case-insensitive `apps_key` / `ctm_key` lookups in `io/localconfig_vdf._load_apps_section` and `io/config_vdf._load_compat_map` exist for this. If you add new VDF readers, do the same — don't trust capitalization.

### Binary vs text VDF

`config.vdf` / `localconfig.vdf` / `appmanifest_*.acf` / `loginusers.vdf` are **text** VDF — handled by `vdf.load()` / `vdf.dump()` in `io/config_vdf.py`, `io/localconfig_vdf.py`, `io/discovery.py`. `shortcuts.vdf` is **binary** VDF — handled by `vdf.binary_load()` / `vdf.binary_dump()` in `io/shortcuts_vdf.py`. The binary format preserves int-vs-string types explicitly; the text format does not. When `cli/shortcuts_cmd.edit` round-trips through JSON, it does so precisely because JSON preserves the int/string distinction that text VDF would lose. `appcache/appinfo.vdf` is yet a different binary format with its own custom parser (`io/appinfo.py`).

## Tests

Tests never touch the real Steam install. The `fake_steam` fixture in `tests/conftest.py` builds a self-contained Steam tree under `tmp_path` (libraryfolders, two app manifests, loginusers, localconfig, config). Tests that need to bypass the production paths set env vars that `cli/_common.py` honors:

- `STEAM_MANAGER_STEAM_ROOT` — overrides the discovered Steam root
- `STEAM_MANAGER_POLICY_PATHS` — colon-separated list of TOML paths (replaces factory + user merge)
- `STEAM_MANAGER_USER_POLICY` — overrides just the user policy path (factory still merged on top)
- `STEAM_MANAGER_BACKUP_ROOT` — overrides `~/.local/state/.../backups`
- `STEAM_MANAGER_SCB_DIR` — overrides the ScopeBuddy configs dir (`~/.config/scopebuddy/games/steam/`)
- `STEAM_MANAGER_FORCE` — when `"1"`, equivalent to passing `--force` (skips Steam-running check)

Commands are exercised through `typer.testing.CliRunner` against `cli.app`. Rich output goes to a `StringIO` in tests, which strips ANSI; substring assertions on table content work, but assertions on colors/styles do not.

`tests/test_architecture.py` enforces the layering rules listed in the Architecture section via AST inspection. If a refactor introduces an import that crosses a forbidden boundary (e.g. `io/` importing from `render`), that test fails before any functional test does — a much cleaner signal than chasing the resulting runtime error.

## Release workflow

```bash
./scripts/build.sh                                                            # produces dist/steam-manager + dist/steam-manager.sha256
./scripts/release.sh vX.Y.Z --notes-file notes.md                             # appends pinned Install section, then `gh release create`
```

`release.sh` exists because the install instructions on a release page must point at *that* release, not at `latest`. The script reads your changelog body from `--notes-file` (or stdin), appends a `## Install` section with `STEAM_MANAGER_VERSION=vX.Y.Z bash` hard-coded, then calls `gh release create` with the binary + sha256 attached. The supplied notes must **not** contain their own `## Install` heading — the script owns it and refuses with an error if one is present. Optional flags: `--title "..."` (default: the tag) and `--draft`.

Both assets must be uploaded — `scripts/install.sh` downloads the `.sha256` next to the binary and verifies it before placing the file. CI on `main` is wired through `.github/workflows/ci.yml`.

The version lives in **two places** that must stay in sync: `pyproject.toml` (`[project] version`) and `src/steam_manager/__init__.py` (`__version__`). The first feeds wheel metadata, the second feeds `--version`. The `test_version_flag_prints_version_and_exits_zero` test catches mismatches.

CI runs `pytest` on a matrix of Python `[3.11, 3.12, 3.13]`. If you bump `requires-python` in `pyproject.toml`, also update the matrix in `.github/workflows/ci.yml`.

The remote is SSH (`git@github.com:MatrixDJ96/steam-manager.git`).

