# steam-manager — Architecture & Internals

This document covers the architecture and internals. For what the tool does
and does not do see
the [README](../README.md).

## 1. Overview

The tool never talks to Steam's servers, never launches games, and never
modifies game files or `appmanifest_*.acf`.

## 2. Goals and non-goals

### Non-goals

- Not a Steam client. Does not launch games, does not authenticate, does not
  talk to Steam's web services.
- Not a Pyroveil manager. Per-game shader/runtime hacks live in
  `~/.pyroveil/` and stay out of scope.
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
└── docs/
    └── ARCHITECTURE.md              # this document
```
