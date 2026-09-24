# steam-manager

[![CI](https://github.com/MatrixDJ96/steam-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/MatrixDJ96/steam-manager/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/MatrixDJ96/steam-manager)](https://github.com/MatrixDJ96/steam-manager/releases/latest)
[![License](https://img.shields.io/github/license/MatrixDJ96/steam-manager)](LICENSE)

A command-line tool to audit and batch-apply policies (Proton compat tool,
launch options) on a local Steam library, with atomic backups and ScopeBuddy
config helpers.

## What it does NOT do

- It is **not** a Steam client. It does not launch games, does not
  authenticate, does not talk to Steam's web services.
- It does **not** modify game files, save data, or `appmanifest_*.acf`.
  Manifests are parsed read-only.
- It is **not** a Pyroveil manager. Per-game shader/runtime hacks in
  `~/.pyroveil/` are out of scope.

Internals are documented in `docs/ARCHITECTURE.md`; build commands and
conventions for contributors and coding agents are in `AGENTS.md`.

## Docs map

| Document                                          | Audience                  | Contents                                                       |
|---------------------------------------------------|---------------------------|----------------------------------------------------------------|
| [README](README.md)                               | Everyone                  | What it is / is not.                                           |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)      | Contributor               | Internals.                                                     |
| [AGENTS.md](AGENTS.md)                            | Contributor, all agents   | Build commands, conventions.                                   |

## License

MIT, in `LICENSE`.
