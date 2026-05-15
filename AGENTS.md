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

- `src/steam_manager/{models,policy,safety,render}.py` — shared dataclasses, the policy merge
  engine, the Steam pid probe, the shared Rich tables, messages and questionary prompts.
- `src/steam_manager/policies.toml` — the factory policy, bundled as package data.
- `tests/conftest.py` — the `fake_steam` fixture, a synthetic Steam tree under `tmp_path`.

## Conventions

- A new VDF reader looks keys up case-insensitively (`io/_vdf_util.ci_get()`): Steam writes
  `Apps` or `apps` depending on the install.
- A version bump changes `pyproject.toml` `[project] version` and `__version__` in
  `src/steam_manager/__init__.py` together: no test compares the two.
- A `requires-python` change updates the Python matrix in `.github/workflows/ci.yml`.

- [README.md](README.md) — what the tool is and is not.
