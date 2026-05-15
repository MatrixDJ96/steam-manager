# steam-manager — How-to guide

Task-oriented recipes for common scenarios. Each recipe assumes you have
`steam-manager` installed (see the [README](../README.md)) and a working
Steam library on Linux.

For the full configuration schema and reference tables, see
[`REFERENCE.md`](REFERENCE.md). For architecture and module internals, see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

Contents:

- Policy: apply one Proton to every game · pick a Proton in the editor · inspect
  or edit the raw policy file · reset to the factory defaults · ignore a game ·
  change the global Proton from the CLI · exclude a few games · preview `apply` ·
  reset one AppID · operate on one account.
- Backups: roll back to the most recent checkpoint.
- Shortcuts and ScopeBuddy: edit non-Steam shortcuts · generate ScopeBuddy stubs ·
  manage ScopeBuddy configs from the dashboard.
- Install and update: pin a release · install into another directory · update
  steam-manager · run from source.

## Apply the same Proton version to every game

```toml
# ~/.config/steam-manager/policies.toml
[games]
compat_tool    = "proton-cachyos-slr"
launch_options = "scopebuddy -- %command%"
```

```bash
steam-manager diff     # preview the changes
steam-manager apply    # commit them (auto-backup first)
```

The exact *tech name* (`"proton-cachyos-slr"`, `"proton_experimental"`, ...)
is the string Steam expects in `config.vdf`; it is not resolved by
`steam-manager`, and a human-friendly display name ("Proton-CachyOS Latest")
silently fails. If you don't know the right tech name, use the editor
(below) — it lists Proton builds actually installed on your system.

## Pick a Proton with the interactive editor

If typing the right `compat_tool` string by hand is error-prone (it is —
Steam silently ignores an unrecognised name), open the editor:

```bash
steam-manager config              # full-screen Textual TUI (default)
steam-manager config --classic    # the step-by-step prompt wizard
```

The **TUI** shows the whole policy on one screen: a defaults bar, a
type-to-filter table of installed games (each with its policy compat tool
and launch options), a targets/backups pane, and a live **Pending** pane.
Move with `↑`/`↓`; `Enter` (or a click) opens the selected game's editor —
compat tool, launch options, ignore — and `e` opens the **Settings** hub
with every global default (games/apps compat and launch, target accounts,
max backups); the defaults cards are clickable too. `Space` toggles
ignore, `/` filters; `s` **Saves**. Quick keys edit without the menus:
`c`/`l` the selected game's compat/launch, `g`/`G` and `p`/`P` the
games/apps defaults, `u` targets, `b` backups. Save writes only
`policies.toml` — the save notice reminds you to run `steam-manager apply`
to push it onto Steam, and the drift line reflects the policy as loaded at
launch. The compat picker lists every
Proton actually installed (custom builds in `compatibilitytools.d/` plus
Steam's own official ones) by display name, so you never type a tech name.

Prefer `--classic` on an exotic terminal, or over SSH where the full TUI
misbehaves. Over a pipe / non-interactive stream, `config` prints the
`get`/`set`/`unset`/`path` hint and exits 2 instead of opening a UI — use
`config set <key> <value>` in scripts.

## Inspect or edit the raw policy file

```bash
steam-manager config path           # where is the file?
$EDITOR $(steam-manager config path)  # open it in your editor
cat $(steam-manager config path)    # print the raw user override file
```

The wizard's "Show current configuration" entry prints the *effective*
config (factory + user, merged) when you want to inspect from inside the
interactive flow.

## Reset your overrides to the factory defaults

The wizard has a "Reset to defaults" entry that does this with a
confirmation prompt. From scripts, the same outcome is one rm:

```bash
rm $(steam-manager config path)
```

The factory defaults are bundled with the binary; removing the user file
makes the tool read them directly.

## Ignore a game without opening the wizard

```bash
steam-manager config set overrides.1495710.ignore true
```

Equivalent to picking that game in the wizard's "Toggle ignore list" entry.
Useful right after `steam-manager list` reveals a game you want excluded:

```bash
steam-manager list | grep HELLDIVERS                       # spot the AppID
steam-manager config set overrides.1495710.ignore true     # one-shot
steam-manager diff                                         # confirm it's gone from drift
```

## Change the global Proton tool from the CLI

```bash
steam-manager config set games.compat_tool "proton_experimental"
steam-manager config get games.compat_tool
```

Type inference: `true`/`false` → bool, digits → int, anything else → string.
User comments in the TOML file are preserved.

## Exclude a few games from a global policy

```toml
[games]
compat_tool = "proton-cachyos-slr"

[overrides.1495710]
ignore = true                  # do not touch HELLDIVERS 2 at all

[overrides.2183900]
launch_options = "DXVK_FRAME_RATE=0 scopebuddy -- %command%"
```

`ignore = true` skips the AppID entirely from `diff`/`apply`. Setting any
other field under `[overrides.<id>]` overrides that single field for that
AppID; unset fields fall back to the section default.

## Inspect what `apply` would change without writing anything

```bash
steam-manager diff
```

`diff` is read-only — no backup is created, no file is touched. Exit code is
`1` when drift is detected, `0` when everything is in sync. Useful for shell
scripts and CI:

```bash
if steam-manager diff > /dev/null; then
    echo "clean"
else
    echo "drift — run steam-manager apply"
fi
```

## Roll back to the most recent checkpoint

```bash
steam-manager restore --last
```

Or pick interactively from the full backup history:

```bash
steam-manager restore        # prompts a single-select list
```

Before extracting, `restore` shows a **preview**: it diffs the archive
contents against the live on-disk state and renders the same compat-tool
and launch-options panels you get from `steam-manager diff`, plus a
Non-Steam shortcuts or ScopeBuddy configs panel when the archive holds
those files. The
columns flip semantically — "From" is the current value, "To" is the
value the restore would put back — but the rendering is the same, so you
can see at a glance which AppIDs are about to change.

If restoring would change no compat tool, launch option, non-Steam
shortcut or ScopeBuddy config (already restored, or never diverged),
`restore` skips the extraction entirely and prints
`would change nothing — already in this state.`

Each `apply`/`clear` creates a `.tar.gz` checkpoint at
`~/.local/state/steam-manager/backups/` before writing. Retention defaults to
the last 10 archives (override via `[general] max_backups`).

## Reset one specific AppID to Steam defaults

There is no built-in single-AppID reset: `clear` wipes every app, and an
empty-string override (`compat_tool = ""`, `launch_options = ""`) enforces
nothing, so `apply --appid <id>` reports no changes and leaves the current
values in place.

## Operate on a single Steam user account

```bash
steam-manager diff --user matrixdj96
steam-manager apply --user matrixdj96
```

Or every local account at once:

```bash
steam-manager apply --all-users
```

CLI flags override `[general] target_users` from `policies.toml`. The
defaults from `policies.toml` are used when no flag is passed.

## Edit non-Steam game shortcuts (the binary `shortcuts.vdf`)

Steam stores user-added non-Steam games (`Add a Non-Steam Game...` from the
Library) in a per-user *binary* file: `<userdata>/<sid3>/config/shortcuts.vdf`.
It's not editable with a normal editor — the values carry int32 vs string
types explicitly.

```bash
steam-manager shortcuts path             # print the file path  (alias: sct)
steam-manager shortcuts show             # print as pretty JSON (read-only)
steam-manager shortcuts edit             # round-trip via JSON in $EDITOR
```

`edit` decodes the binary into a temporary JSON file, opens `$EDITOR`, then
re-encodes back to the binary format atomically — preserving int types
(critical: `appid` must stay an int, not become a string). A `.tar.gz`
checkpoint of the original file is taken before writing, so `steam-manager
restore` can roll back.

Typical use: setting `LaunchOptions` to `scopebuddy -- %command%` on a
non-Steam game, or fixing the `Exe` path after relocating an AppImage.

```bash
steam-manager shortcuts edit             # active account (or interactive picker)
steam-manager shortcuts edit --user me   # specific account
steam-manager shortcuts edit --force     # bypass the Steam-running check (risky)
```

**Steam must be closed** during the write — Steam keeps `shortcuts.vdf` in
memory and rewrites it on exit, so any edit made while Steam is running gets
clobbered. The default Steam-running check protects against this; `--force`
disables it (don't unless you know what you're doing).

## Generate ScopeBuddy stubs for every game with `scopebuddy --` in its launch options

```bash
steam-manager scopebuddy observe   # see which games are missing a stub (alias: scb)
steam-manager scopebuddy init --missing
```

The stub is intentionally minimal — two comment lines — so you can fill it
in by hand later. Run `steam-manager scopebuddy observe` again to verify
nothing is missing.

## Manage ScopeBuddy configs from the dashboard

On an interactive terminal the bare command opens a full-screen dashboard:

```bash
steam-manager scopebuddy           # dashboard TUI on a terminal (alias: scb)
```

The dashboard lists every installed game with whether its launch options
use scopebuddy and whether its per-game `.conf` exists,
plus a separate table of orphan configs (a `.conf` with no matching installed
game). A `<name>.local.conf` is ScopeBuddy's local override of `<name>.conf`:
it rides its base config and gets no row of its own — it only appears when the
base file is absent (a dangling override). Move with `↑`/`↓`; `/` filters the
games table, `r` reloads from disk, `q` quits.

- `Enter` (or a click) on a row opens its action modal: create the L1 stub,
  open the `.conf` in `$EDITOR`, or delete an orphan config.
- `i` bulk-creates a stub for every game whose launch options use scopebuddy
  but that has no `.conf`, after a confirmation.
- Deleting an orphan config writes a `.tar.gz` checkpoint first, so
  `steam-manager restore` rolls it back.

Over a pipe or a non-interactive stream the same command prints the scriptable
`observe` report instead. `STEAM_MANAGER_SCB_UI=tui|observe` forces a
front-end, and `steam-manager scopebuddy observe` prints the report on any
terminal:

```bash
steam-manager scopebuddy observe   # missing/orphan report, exit 1 on issues
```

## Update steam-manager itself

```bash
steam-manager update            # interactive: shows release notes, then prompts
steam-manager update --check    # is there a new version? (no download)
steam-manager update --yes      # non-interactive: skip prompt
steam-manager update --force    # reinstall the same version
```

```text
A new release of steam-manager is available: 1.0.0 → 1.0.1
To upgrade, run: steam-manager update
https://github.com/MatrixDJ96/steam-manager/releases/tag/v1.0.1
```

To silence the hint, set `STEAM_MANAGER_NO_UPDATE_NOTIFIER=1` in your
shell profile. The hint is also silent in non-TTY contexts (pipes, CI) and
when running from source.

## Run from source for development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # hermetic suite (-m "not tui" skips the Textual Pilot tests)
```

The repository's `AGENTS.md` lists the build commands, conventions and
gotchas for contributors (`rich-click` integration, VDF case-insensitivity,
the frozen-binary TUI check).
