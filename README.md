# steam-manager

[![CI](https://github.com/MatrixDJ96/steam-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/MatrixDJ96/steam-manager/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/MatrixDJ96/steam-manager)](https://github.com/MatrixDJ96/steam-manager/releases/latest)
[![License](https://img.shields.io/github/license/MatrixDJ96/steam-manager)](LICENSE)

A command-line tool to audit and batch-apply policies (Proton compat tool,
launch options) on a local Steam library, with atomic backups and ScopeBuddy
config helpers.

## What it does

- Discovers every installed game across all Steam library folders.
- Expresses the desired state declaratively in `policies.toml`, with per
  app-type sections and per-AppID overrides.
- Takes an atomic `.tar.gz` checkpoint before every `apply`, `clear`, and
  `shortcuts edit`, with an interactive restore command.
- Edits Steam's binary `shortcuts.vdf` (non-Steam games) via a JSON
  round-trip in `$EDITOR`, preserving int32/string typing.

## What it does NOT do

- It is **not** a Steam client. It does not launch games, does not
  authenticate, does not talk to Steam's web services.
- It does **not** resolve or validate Proton names — the `compat_tool` value
  is written to Steam verbatim, and Steam silently ignores a name it doesn't
  recognize. Use the *tech name* (e.g. `proton-cachyos-slr`), not the display
  name; the `config` editor picks the right one for you.
- It does **not** modify game files, save data, or `appmanifest_*.acf`.
  Manifests are parsed read-only.
- It is **not** a Pyroveil manager. Per-game shader/runtime hacks in
  `~/.pyroveil/` are out of scope.

## Configuration

A factory `policies.toml` ships with the binary. Your overrides live at
`~/.config/steam-manager/policies.toml` and are deep-merged on top.

```toml
[games]
compat_tool    = "proton-cachyos-slr"
launch_options = "scopebuddy -- %command%"

[overrides.1495710]
ignore = true                  # exclude one AppID entirely

[overrides.2183900]
launch_options = "DXVK_FRAME_RATE=0 scopebuddy -- %command%"
```

## Safety

- **Steam must be closed** while you `apply`, `restore`, `clear`, or
  `shortcuts edit`. The tool detects a running Steam via
  `~/.steam/steam.pid` and refuses to run. Use `--force` to override.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                         # hermetic suite (-m "not tui" skips the Textual Pilot tests)
```

Internals are documented in `docs/ARCHITECTURE.md`; build commands and
conventions for contributors and coding agents are in `AGENTS.md`.

## Docs map

| Document                                          | Audience                  | Contents                                                       |
|---------------------------------------------------|---------------------------|----------------------------------------------------------------|
| [README](README.md)                               | Everyone                  | What it is / is not.                                           |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)      | Contributor               | Internals.                                                     |
| [AGENTS.md](AGENTS.md)                            | Contributor, all agents   | Build commands, conventions, gotchas.                          |

## License

MIT, in `LICENSE`.
