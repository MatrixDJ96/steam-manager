# steam-manager — CLI that audits and applies policies on a local Steam library

## Build & run

```bash
python3 -m venv .venv && source .venv/bin/activate
```

CI (`.github/workflows/ci.yml`) runs `pytest` on Python 3.11, 3.12 and 3.13 for pushes and
pull requests to `main`. `scripts/build.sh` activates `.venv` unless a venv is already active.

## Conventions

- A `requires-python` change updates the Python matrix in `.github/workflows/ci.yml`.

- [README.md](README.md) — what the tool is and is not.
