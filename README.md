# steam-manager

[![CI](https://github.com/MatrixDJ96/steam-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/MatrixDJ96/steam-manager/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/MatrixDJ96/steam-manager)](https://github.com/MatrixDJ96/steam-manager/releases/latest)
[![License](https://img.shields.io/github/license/MatrixDJ96/steam-manager)](LICENSE)

A command-line tool to audit and batch-apply policies (Proton compat tool,
launch options) on a local Steam library, with atomic backups and ScopeBuddy
config helpers.

Set one Proton version and one launch-options string across your **entire**
library in a single command, with per-AppID exceptions and an automatic
safety checkpoint before every write. Doing the same through the Steam UI
takes one right-click per game.

## Demo

```text
$ steam-manager diff
ⓘ Target users: user:matrixdj96 (active)
╭─ Compat tool ────────────────────────────────────────────────────────────────╮
│      AppID    Name            From         To                                │
│        222    Game Two        <none>       Proton-CachyOS Latest             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Launch options ─────────────────────────────────────────────────────────────╮
│      AppID    Name            From         To                                │
│        222    Game Two        <none>       scopebuddy -- %command%           │
╰──────────────────────────────────────────────────────────────────────────────╯

ⓘ 2 changes planned. Run `steam-manager apply` to apply.
```

`diff` is read-only. `apply` writes the changes after taking a `.tar.gz`
checkpoint. Both rows would render in **bold** on a real terminal because
they drift from the policy; conforming rows render dim.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh | bash
```

or with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh | bash
```

Re-running the command at any time replaces the binary with the latest
release. To uninstall: `rm ~/.local/bin/steam-manager`.

**Requirements**: Linux x86_64, `curl` or `wget`. No Python or `pip` needed —
the binary is fully self-contained (~16 MB).

The installer downloads the binary into `~/.local/bin/` and verifies it
against the published `.sha256`. If the directory is not on your `PATH`, the
installer prints the line to add to your shell profile.

### Pin a specific version

```bash
curl -fsSL https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh \
    | STEAM_MANAGER_VERSION=v0.0.1 bash
```

The variable goes **before `bash`**, not before `curl` — the installer is the
bash subprocess, and a prefix on `curl` would only enter `curl`'s environment.

## Usage

### First run

```bash
steam-manager config           # interactive wizard: pick Proton, set defaults, etc.
steam-manager diff             # preview what would change (read-only)
steam-manager apply            # commit the changes (auto-backup first)
```

### Day-to-day

```bash
steam-manager list             # what is installed and how it is configured now
steam-manager diff             # what `apply` would change
steam-manager apply            # apply the policy
```

### Tweak the policy

```bash
steam-manager config                                   # interactive wizard (default)
steam-manager config get games.compat_tool             # read a value (scriptable)
steam-manager config set games.compat_tool "Proton-X"  # set a value  (scriptable)
steam-manager config unset overrides.1495710.ignore    # remove a key (scriptable)
```

### Backups

```bash
steam-manager backup           # manual checkpoint
steam-manager restore --last   # roll back to the most recent
steam-manager restore          # interactive picker
```

### ScopeBuddy helpers

```bash
steam-manager scopebuddy       # find missing or orphan configs (alias: scb)
steam-manager scopebuddy init  # generate missing stubs
```

### Non-Steam shortcuts

```bash
steam-manager shortcuts show   # print the binary shortcuts.vdf as JSON
steam-manager shortcuts edit   # round-trip via JSON in $EDITOR (safe re-encode)
```

For per-scenario recipes (per-AppID exceptions, multi-user setups, scripting
patterns) see [`docs/HOWTO.md`](docs/HOWTO.md). For the complete schema,
flags, and exit codes see [`docs/REFERENCE.md`](docs/REFERENCE.md).

## What it does

- Discovers every installed game across all Steam library folders.
- Reads and writes the per-app Proton compatibility tool (`config.vdf`).
- Reads and writes per-user launch options (`localconfig.vdf`).
- Expresses the desired state declaratively in `policies.toml`, with per
  app-type sections and per-AppID overrides.
- Takes an atomic `.tar.gz` checkpoint before every destructive operation,
  with an interactive restore command.
- Operates on the active local account, on a specific account, or on all
  local accounts.
- Observes ScopeBuddy per-game stubs and generates them on demand.
- Edits Steam's binary `shortcuts.vdf` (non-Steam games) via a JSON
  round-trip in `$EDITOR`, preserving int32/string typing.

## What it does NOT do

- It is **not** a Steam client. It does not launch games, does not
  authenticate, does not talk to Steam's web services.
- It does **not** resolve abstract Proton names — a value like
  `"Proton-CachyOS Latest"` is written to Steam verbatim; Steam resolves it.
- It does **not** modify game files, save data, or `appmanifest_*.acf`.
  Manifests are parsed read-only.
- It is **not** a Pyroveil manager. Per-game shader/runtime hacks in
  `~/.pyroveil/` are out of scope.

## Configuration

A factory `policies.toml` ships with the binary. Your overrides live at
`~/.config/steam-manager/policies.toml` and are deep-merged on top.

Three ways to edit them:

- `steam-manager config` — interactive wizard with picker-based prompts
  (lists the Proton builds actually installed on your system; you don't
  have to type the right tech name by hand).
- `steam-manager config set games.compat_tool "Proton-Experimental"` —
  script-friendly primitives (`get` / `set` / `unset` over dotted keys).
- `$EDITOR $(steam-manager config path)` — edit the raw TOML by hand.

Minimal example:

```toml
[games]
compat_tool    = "Proton-CachyOS Latest"
launch_options = "scopebuddy -- %command%"

[overrides.1495710]
ignore = true                  # exclude one AppID entirely

[overrides.2183900]
launch_options = "DXVK_FRAME_RATE=0 scopebuddy -- %command%"
```

The full schema, per-user filters, exit codes, and environment variables are
documented in [`docs/REFERENCE.md`](docs/REFERENCE.md).

## Safety

- **Steam must be closed** while you `apply`, `restore`, or `clear`. The
  tool detects a running Steam via `~/.steam/steam.pid` and refuses to run.
  Use `--force` to override.
- Every destructive command writes a `.tar.gz` checkpoint to
  `~/.local/state/steam-manager/backups/` **before** touching anything —
  there is no opt-out. Restore with `steam-manager restore`.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                         # 223 tests, all hermetic, < 2 seconds
```

Architecture, module APIs, and the build pipeline are documented in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Project-specific quirks for
contributors (NTFS+btrfs venv, `rich-click` integration, VDF
case-insensitivity) live in [`CLAUDE.md`](CLAUDE.md).

## Docs map

| Document                                          | Audience                  | Contents                                                       |
|---------------------------------------------------|---------------------------|----------------------------------------------------------------|
| [README](README.md)                               | Everyone                  | Quickstart, install, demo, what it is / is not.                |
| [docs/HOWTO.md](docs/HOWTO.md)                    | Operator                  | Cookbook recipes for common scenarios.                         |
| [docs/REFERENCE.md](docs/REFERENCE.md)            | Operator, scripter        | Full configuration schema, exit codes, env vars, terminal compat. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)      | Contributor               | Internals: module reference, backup format, build pipeline.    |
| [CLAUDE.md](CLAUDE.md)                            | Contributor, Claude Code  | Repo quirks and conventions.                                   |

## License

[MIT](LICENSE).
