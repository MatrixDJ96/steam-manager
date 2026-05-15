# steam-manager — CLI that audits and applies policies on a local Steam library

A Python 3.11+ Typer CLI, with Textual TUIs for `config` and `scopebuddy`, that reconciles
Steam's VDF configuration with `policies.toml` and ships as a PyInstaller single-file binary.
Its write commands act on the live Steam install of the machine they run on.

## Build & run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,build]"       # dev: the pytest stack; build: PyInstaller
pytest                              # full suite, hermetic
pytest -m "not tui"                 # fast lane: skips the Textual Pilot tests
pytest tests/test_architecture.py   # import-layering invariants only
steam-manager --version             # proves the editable install resolves
./scripts/build.sh                  # dist/steam-manager + dist/steam-manager.sha256
```

CI (`.github/workflows/ci.yml`) runs `pytest` on Python 3.11, 3.12 and 3.13 for pushes and
pull requests to `main`. `scripts/build.sh` activates `.venv` unless a venv is already active.

## Layout

- `src/steam_manager/cli/` — one `<verb>_cmd.py` per command or sub-typer, wired by
  side-effect imports in `cli/__init__.py`; `cli/_*.py` are the shared CLI helpers.
- `src/steam_manager/cli/tui/` — the Textual front-ends (`config` editor, `scopebuddy`
  dashboard), the only package that imports `textual`.
- `src/steam_manager/io/` — VDF, policy TOML, backup, ScopeBuddy and compat-tool file I/O and
  the GitHub releases client, no Typer or Rich.
- `src/steam_manager/{models,policy,safety,render}.py` — shared dataclasses, the policy merge
  engine, the Steam pid probe, the shared Rich tables, messages and questionary prompts.
- `src/steam_manager/policies.toml` — the factory policy, bundled as package data.
- `tests/conftest.py` — the `fake_steam` fixture, a synthetic Steam tree under `tmp_path`.

## Conventions

- An import across `cli/`, `io/` and the core modules follows the layer rules in
  `docs/ARCHITECTURE.md` §7; `tests/test_architecture.py` fails first when one is broken.
- A new destructive operation takes its checkpoint through `cli/_checkpoint.make_checkpoint()`
  with its own `trigger`, never a hand-built manifest: `restore` reads that one schema.
- A new VDF reader looks keys up case-insensitively (`io/_vdf_util.ci_get()`): Steam writes
  `Apps` or `apps` depending on the install.
- A change to what counts as a game goes into `policy.section_for_type()`, `io/appinfo.parse()`
  or the name-prefix fallback `cli/_appinfo.NON_GAME_NAME_PREFIXES`, not into a filter in
  `cli/_drift.compute_drift()`: `list`, `diff`, `apply`, `config` and `scopebuddy` all filter
  through `cli/_appinfo.is_listable()`.
- A dependency PyInstaller cannot trace is declared in `scripts/build.sh` with
  `--hidden-import` or `--collect-submodules`, as the lazy `textual.widgets` modules are.
- A version bump changes `pyproject.toml` `[project] version` and `__version__` in
  `src/steam_manager/__init__.py` together: no test compares the two.
- A `requires-python` change updates the Python matrix in `.github/workflows/ci.yml`.

## Gotchas

- Without `--collect-submodules textual` in `scripts/build.sh`, importing `Tab`, `TabPane` or
  `MarkdownViewer` from `textual.widgets` fails only in the frozen binary: their loader
  modules are not traced. Keep the flag; the measurement is in `docs/ARCHITECTURE.md` §6.
- `cli/_rich.py` swaps the `__class__` of Typer's Click commands for rich-click's, and plain
  Typer help loses the aligned `--help` columns: keep the rich-click integration and the
  `click`/`typer`/`rich-click` pins in `pyproject.toml`.
- `CliRunner` output loses Rich's ANSI styles: assert on text, never on color or bold.
- `shortcuts.vdf` is binary VDF with explicit int/string types (`io/shortcuts_vdf.py`); text
  VDF drops them, which is why `shortcuts edit` round-trips through JSON.
- Bare `steam-manager scopebuddy` opens the dashboard only when stdin and stdout are both TTYs
  (`cli/_config_entry._ui_is_interactive()`), else it runs `observe`.
  `STEAM_MANAGER_SCB_UI=tui` skips that check, and so does a non-tty stream reported as
  interactive, as in some agent harnesses: the dashboard then renders into the stream and
  blocks. There, run `steam-manager scopebuddy observe`.

## Boundaries

- `apply`, `clear`, `restore`, `shortcuts edit`, `scopebuddy init` and the dashboard's init and
  delete rewrite the live Steam and ScopeBuddy files of this machine: without the owner's go,
  point `STEAM_MANAGER_STEAM_ROOT`, `STEAM_MANAGER_BACKUP_ROOT` and `STEAM_MANAGER_SCB_DIR` at
  a scratch tree, or stay on `list`, `diff` and `scopebuddy observe`.
- `config set`, `config unset` and the `config` editor's save and reset write or delete the
  user policy: without the owner's go, point `STEAM_MANAGER_USER_POLICY` at a scratch file.

## Docs

- [README.md](README.md) — what the tool is and is not.
- [docs/HOWTO.md](docs/HOWTO.md) — task recipes; a new user workflow gets its recipe here.
- [docs/REFERENCE.md](docs/REFERENCE.md) — policy schema, commands and flags, exit codes,
  environment variables; every user-visible flag or variable is documented here.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module reference, layer rules, backup
  format, build pipeline, the test environment overrides; internal API details go here.
