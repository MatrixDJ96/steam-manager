# steam-manager — How-to guide

Task-oriented recipes for common scenarios. Each recipe assumes you have
`steam-manager` installed (see the [README](../README.md)) and a working
Steam library on Linux.

For the full configuration schema and reference tables, see
[`REFERENCE.md`](REFERENCE.md). For architecture and module internals, see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Apply the same Proton version to every game

```toml
# ~/.config/steam-manager/policies.toml
[games]
compat_tool    = "Proton-CachyOS Latest"
launch_options = "scopebuddy -- %command%"
```

```bash
steam-manager diff     # preview the changes
steam-manager apply    # commit them (auto-backup first)
```

The exact name (`"Proton-CachyOS Latest"`, `"proton_experimental"`, ...) is
the string Steam expects in `config.vdf`; it is not resolved by
`steam-manager`. If you don't know the right tech name, use the wizard
(below) — it lists Proton builds actually installed on your system.

## Pick a Proton with an interactive wizard

If typing the right `compat_tool` string by hand is error-prone (it is —
Steam silently ignores an unrecognised name), run the wizard:

```bash
steam-manager config wizard
```

The wizard runs a *show + targeted edit + confirm* loop: it first prints
the current effective config, then lets you pick an area to edit (compat
& launch / general / ignore list / reset), walks you through picker-based
prompts with the current value pre-selected, shows a yellow diff table
of what would change, and asks `Apply changes? Y/n` before writing. Then
it loops back to the menu, so you can chain edits in one session and
abort any one of them without leaving the wizard.

For compat tool, the picker lists every Proton found in
`~/.steam/compatibilitytools.d/` (custom: GE-Proton, Proton-CachyOS, ...)
plus every Proton installed by Steam itself as an app (official:
Experimental, 9.0, ...), showing both the human display name and the
tech name that Steam recognises in `config.vdf`. `[current]` marks the
one currently active.

Prefer the wizard when you don't already know the exact value to write;
prefer `config set <key> <value>` when you do.

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
steam-manager config set games.compat_tool "Proton-9.0"
steam-manager config get games.compat_tool
```

Type inference: `true`/`false` → bool, digits → int, anything else → string.
User comments in the TOML file are preserved.

## Exclude a few games from a global policy

```toml
[games]
compat_tool = "Proton-CachyOS Latest"

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
and launch-options panels you get from `steam-manager diff`. The
columns flip semantically — "From" is the current value, "To" is the
value the restore would put back — but the rendering is the same, so you
can see at a glance which AppIDs are about to change.

If the archive is byte-identical to the live state (already restored, or
never diverged), `restore` skips the extraction entirely and prints
`would change nothing — already in this state.`

Each `apply`/`clear` creates a `.tar.gz` checkpoint at
`~/.local/state/steam-manager/backups/` before writing. Retention defaults to
the last 20 archives (override via `[general] max_backups`).

## Reset one specific AppID to Steam defaults

There is no built-in single-AppID reset, but you can compose two existing
commands: scope `clear` to the AppID via the policy override, or directly
use the per-AppID `diff`/`apply` flag.

```bash
# Method 1: ad-hoc policy override
cat >> ~/.config/steam-manager/policies.toml <<'EOF'

[overrides.2183900]
compat_tool    = ""              # empty string = remove
launch_options = ""
EOF

steam-manager apply --appid 2183900
```

```bash
# Method 2: full clear scoped to a single AppID — not currently supported.
# Use Method 1 above.
```

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
steam-manager scopebuddy        # see which games are missing a stub (alias: scb)
steam-manager scopebuddy init --missing
```

The stub is intentionally minimal — two comment lines — so you can fill it
in by hand later. Run `steam-manager scopebuddy` again to verify nothing is
missing.

## Pin to a specific release when installing on a new machine

```bash
curl -fsSL https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh \
    | STEAM_MANAGER_VERSION=v0.1.0 bash
```

Useful in `Dockerfile`s and provisioning scripts where you want a
reproducible install. The installer downloads `steam-manager.sha256`
alongside the binary and verifies the checksum before placing the file.

Note the prefix is on **`bash`**, not on `curl`. In a pipeline the two
processes are forked independently and a `VAR=value curl ... | bash` only
sets `VAR` in `curl`'s environment, which the installer never sees — it
silently falls back to `latest`. If you prefer, `export STEAM_MANAGER_VERSION=v0.1.0`
once and then pipe normally works too.

## Install into a non-standard directory

```bash
STEAM_MANAGER_INSTALL_DIR=/opt/bin \
    curl -fsSL https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh | bash
```

Add the directory to your `PATH` if it is not already there (the installer
prints the exact line to add).

## Update steam-manager itself

```bash
steam-manager update            # interactive: shows release notes, then prompts
steam-manager update --check    # is there a new version? (no download)
steam-manager update --yes      # non-interactive: skip prompt
steam-manager update --force    # reinstall the same version
```

`update` pulls the latest release tag from GitHub, renders the release
notes inline (Rich Markdown), and — on confirmation — fetches a fresh copy
of `scripts/install.sh` from `main` and runs it. The script handles the
download, SHA-256 verify, and atomic swap on the same filesystem as the
running binary (Linux unlink-while-mmap semantics make this safe).

Available only on the PyInstaller binary distribution. If you installed
from source (`pip install -e .` or `pip install steam-manager`), the
command refuses with a clear message — use `pip install -U` or `git pull`
instead.

After 24 hours from the last check, any subsequent command prints a one-shot
hint on stderr when a newer release exists:

```text
A new release of steam-manager is available: 0.1.0 → 0.1.1
To upgrade, run: steam-manager update
https://github.com/MatrixDJ96/steam-manager/releases/tag/v0.1.1
```

To silence the hint, set `STEAM_MANAGER_NO_UPDATE_NOTIFIER=1` in your
shell profile. The hint is also silent in non-TTY contexts (pipes, CI).

## Run from source for development

```bash
python3 -m venv ~/.venvs/steam-manager   # keep site-packages off NTFS
ln -sf ~/.venvs/steam-manager .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 223 hermetic tests, &lt;2s
```

The repository's `CLAUDE.md` documents project-specific quirks (NTFS+btrfs
venv layout, `rich-click` integration, VDF case-insensitivity).
