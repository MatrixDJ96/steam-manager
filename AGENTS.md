# steam-manager — CLI that audits and applies policies on a local Steam library

## Build & run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,build]"       # dev: the pytest stack; build: PyInstaller
pytest                              # full suite, hermetic
```

CI (`.github/workflows/ci.yml`) runs `pytest` on Python 3.11, 3.12 and 3.13 for pushes and
pull requests to `main`. `scripts/build.sh` activates `.venv` unless a venv is already active.

## Layout

- `src/steam_manager/io/` — VDF, policy TOML, backup, ScopeBuddy and compat-tool file I/O and
  the GitHub releases client, no Typer or Rich.
- `src/steam_manager/{models,policy,safety,render}.py` — shared dataclasses, the policy merge
  engine, the Steam pid probe, the shared Rich tables, messages and questionary prompts.
- `src/steam_manager/policies.toml` — the factory policy, bundled as package data.
- `tests/conftest.py` — the `fake_steam` fixture, a synthetic Steam tree under `tmp_path`.

## Conventions

- A new destructive operation takes its checkpoint through `cli/_checkpoint.make_checkpoint()`
  with its own `trigger`, never a hand-built manifest: `restore` reads that one schema.
- A new VDF reader looks keys up case-insensitively (`io/_vdf_util.ci_get()`): Steam writes
  `Apps` or `apps` depending on the install.
- A version bump changes `pyproject.toml` `[project] version` and `__version__` in
  `src/steam_manager/__init__.py` together: no test compares the two.
- A `requires-python` change updates the Python matrix in `.github/workflows/ci.yml`.

## Gotchas

- `cli/_rich.py` swaps the `__class__` of Typer's Click commands for rich-click's, and plain
  Typer help loses the aligned `--help` columns: keep the rich-click integration and the
  `click`/`typer`/`rich-click` pins in `pyproject.toml`.
- `shortcuts.vdf` is binary VDF with explicit int/string types (`io/shortcuts_vdf.py`); text
  VDF drops them, which is why `shortcuts edit` round-trips through JSON.

- [README.md](README.md) — what the tool is and is not.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module reference and backup format; internal
  API details go here.
