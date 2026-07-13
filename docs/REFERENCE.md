# steam-manager — Reference

Exhaustive reference for configuration, commands, exit codes, environment
variables, and terminal compatibility. For task-oriented recipes see
[`HOWTO.md`](HOWTO.md); for architecture and module internals see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Configuration file

The factory `policies.toml` ships as a package resource inside the binary.
User overrides live at `~/.config/steam-manager/policies.toml` and are
deep-merged on top of the factory file:

- scalars and lists are replaced wholesale,
- nested tables are merged recursively.

### Full schema

```toml
[general]
max_backups  = 10
# target_users — special values:
#   ["active"]      -> only the MostRecent=1 account in loginusers.vdf
#   ["matrixdj96"]  -> a specific account
#   ["*"]           -> every local account
#   ["a", "b"]      -> explicit list
target_users = ["active"]

[games]
# Applied to every app of type "game" or "beta". compat_tool is the tech
# name Steam expects (a display name like "Proton-CachyOS Latest" is
# silently ignored by Steam) — the `config` editor picks the right one.
compat_tool    = "proton-cachyos-slr"
launch_options = "scopebuddy -- %command%"

[applications]
# Applied to every app of type "application" (Lossless Scaling, OBS, ...).
# Leave empty -> diff/apply enforce nothing for these apps; they still appear
# in `list` but contribute no drift.

[overrides.&lt;appid&gt;]
# Per-AppID override. Special key:
#   ignore = true              skip this AppID from diff/apply
# Any other field overrides the section value for that AppID.
```

An omitted field in a section means *do not enforce*: diff/apply ignore that
field for matching apps, but they remain visible under `list`.

## App-type mapping

Each app's `common.type` (read from Steam's binary `appinfo.vdf` cache) maps
to a policy section:

| `common.type` value                                                                               | Policy section   | Notes                              |
|---------------------------------------------------------------------------------------------------|------------------|------------------------------------|
| `game`, `beta`                                                                                    | `[games]`        | Standard games and closed betas    |
| `application`                                                                                     | `[applications]` | Utilities (Lossless Scaling, ...)  |
| `dlc`, `music`, `tool`, `demo`, `video`, `config`, `hardware`, `series`, `mod`, `plugin`, `media` | (excluded)       | Skipped everywhere                 |
| unknown / missing                                                                                 | `[games]`        | Fallback                           |

When the cache is missing or misclassifies an app, a name-prefix fallback
filters out common non-game patterns (soundtracks, OSTs, etc.).

## Commands

Same five panels as `steam-manager --help`.

### Inspect

| Command  | Description |
|----------|-------------|
| `list`   | List installed games with compat tool and per-user launch options, split into **Games** and **Applications** panels by Steam app type. Drift rows are **bold**, conforming rows are **dim**. AppID and Name cells are clickable OSC 8 links. `--json` outputs machine-readable JSON instead of the table (ungrouped, flat list). |
| `diff`   | Show planned changes vs policy (read-only). Panels are labelled `Games · …` / `Applications · …` when changes span both kinds. Exits 1 if drift exists. |

### Apply

| Command  | Description |
|----------|-------------|
| `apply`  | Apply planned changes. Creates an auto-backup checkpoint; aborts if Steam is running (use `--force` to bypass). |
| `clear`  | Wipe ALL compat tool overrides + launch options for every app (no type filter). Auto-backup. `--yes` skips the confirmation prompt; `--force` bypasses the Steam-running check. |

### Backup

| Command   | Description |
|-----------|-------------|
| `backup`  | Manually create a full checkpoint archive. |
| `restore` | Restore from a previous checkpoint. Interactive single-select or `--last`; `--yes` skips the confirmation. Aborts if Steam is running. |

### Steam tools

| Command              | Description |
|----------------------|-------------|
| `scopebuddy` / `scb` | Manage per-game ScopeBuddy configs. The bare command opens the dashboard TUI on an interactive terminal and prints the `observe` report over a pipe (`STEAM_MANAGER_SCB_UI=tui\|observe` forces one). Sub-commands: `observe` (missing/orphan report), `init` (per AppID, `--missing`, interactive). `scb` is a short hidden alias. |
| `shortcuts` / `sct`  | Edit Steam's binary `shortcuts.vdf` (non-Steam games). `path`, `show`, `edit`. `sct` is a short hidden alias. |
| `open &lt;appid&gt;`       | Open the game's install folder (or `--compat` for compatdata) via `xdg-open`. |

### Manage

| Command  | Description |
|----------|-------------|
| `config` | Edit and inspect the user policy file (`~/.config/steam-manager/policies.toml`). With no sub-command, opens the interactive editor — the **Textual TUI** by default, or the classic prompt wizard with `--classic`. Sub-commands: `get`, `set`, `unset`, `wizard`, `path`. |
| `update` | Self-update the binary to the latest GitHub release. `--check` (read-only), `--yes` (skip prompt), `--force` (reinstall same version). PyInstaller-only. |

### Global options

| Option              | Description                                          |
|---------------------|------------------------------------------------------|
| `--version`         | Print version (`steam-manager X.Y.Z`) and exit.      |
| `--help`            | Print help for the command.                          |

### `config` sub-command

Edit and inspect the user policy file at
`~/.config/steam-manager/policies.toml` without leaving the shell. All
modifying operations preserve user comments (via `tomlkit`).

| Sub-command                         | Behavior                                                                                                |
|-------------------------------------|---------------------------------------------------------------------------------------------------------|
| `config` *(no sub-command)*         | Opens the interactive editor — Textual TUI by default, classic wizard with `--classic`. Non-TTY → exit 2 + scriptable hint. |
| `config get <key>`                  | Print the effective value at a dotted key (factory + user merged). Exit 3 if missing.                   |
| `config set <key> <value>`          | Set a dotted key. Type inference: `true`/`false` → bool, digits → int, else string.                     |
| `config unset <key>`                | Remove a dotted key. Drops the parent table if it becomes empty.                                        |
| `config wizard`                     | Explicit form of bare `config`. Accepts `--tui` / `--classic`.                                          |
| `config path`                       | Print the user policy file path. Useful for `cat $(steam-manager config path)` or `$EDITOR $(...)`.     |

The editor front-end is chosen, in order, by: an explicit `--tui` / `--classic`
flag (mutually exclusive — both → exit 2), then `STEAM_MANAGER_CONFIG_UI=tui|classic`,
then the built-in default (`tui`). On a non-interactive stream (a pipe, CI),
`config` never launches a UI: it prints the `get`/`set`/`unset`/`path` hint and
exits 2. The full-screen TUI shows the whole policy on one screen (defaults,
a filterable games table, targets, a live Pending pane); **Save** writes
`policies.toml` only — run `steam-manager apply` to push it onto Steam. The
classic prompt flow below is reached via `--classic`.

Dropped sub-commands (covered by the wizard or by external tools):

- `config show` → wizard entry "Show current configuration".
- `config edit` → `$EDITOR $(steam-manager config path)`.
- `config reset` → wizard entry "Reset to defaults", or `rm $(steam-manager config path)`.
- `config ignore <appid>` → wizard entry "Toggle ignore list", or `config set overrides.<appid>.ignore true`.

#### Classic wizard flow (`--classic`)

The classic wizard is a flat menu of granular actions — every entry takes you directly to the relevant picker, with no intermediate "scope / target" cascade. Each iteration:

1. **Pick an action** from the main menu (see table below). The cursor re-opens on the entry you last chose. `Esc` at the main menu exits; `Esc` inside a picker (or its `← Back` entry) returns to the menu.
2. **A breadcrumb header** shows `Editing: <setting> — [<scope>]` and the current value, so the picker always has context.
3. **The picker** opens grouped by source where it makes sense (compat tool → `── Custom ── / ── Official ── / ── Special ──`; launch options → `── Templates ── / ── Special ──`). The cursor is pre-positioned on the current value.
4. **The edit is queued**, not written. Edits accumulate so you can make several before committing; re-picking a key's on-disk value cancels its queued edit.

Queued edits are written in one batch only when you choose **Apply pending changes (N)** (which appears, with a count, once at least one edit is queued); **Discard pending changes (N)** drops them. Exiting with unapplied edits asks for confirmation first. The current-configuration table is **not** rendered automatically; it's behind the explicit "Show current configuration" menu entry (which also lists any queued edits), so the default screen is just the menu.

| Menu entry                                | What it does                                                                                                                  |
|-------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| Change Proton (default for all games)     | Writes `games.compat_tool`. Picker grouped by source.                                                                         |
| Change Proton (for one game)              | Asks which installed game, then writes `overrides.<appid>.compat_tool`.                                                       |
| Change launch options (default…)          | Writes `games.launch_options` from a template list or freeform input.                                                         |
| Change launch options (for one game)      | Asks which game, then writes `overrides.<appid>.launch_options`.                                                              |
| Toggle ignore list                        | Multi-select over installed games; pre-checked = currently ignored. Diffs the two sets and emits add/remove changes.          |
| Set target users                          | Pick one mode — `active` (logged-in), `*` (all accounts), or "Specific accounts…"; the last opens a multi-select over the `loginusers.vdf` accounts. The modes are mutually exclusive. Writes `general.target_users`. |
| Set max backups                           | Integer prompt (≥ 1). Writes `general.max_backups`.                                                                           |
| Show current configuration                | Renders the full effective config as a sectioned table. No write.                                                             |
| Reset to defaults                         | Deletes `~/.config/steam-manager/policies.toml` after explicit confirmation. Same outcome as `rm $(steam-manager config path)`. |

Non-runnable compat tools — Steam Linux Runtime layers (`scout_ldlp` / "Legacy runtime") and Proton sub-runtimes invoked internally for anti-cheat ("Proton EasyAntiCheat Runtime", "Proton BattlEye Runtime") — are filtered out of the picker. They're installed on disk but selecting them as a game's compat_tool is never what you want.

Dotted keys: `games.compat_tool`, `general.max_backups`, `overrides.1495710.ignore`. Keys containing literal `.` are not supported.

### Shared user filters

`diff`, `apply`, `list`, `scopebuddy`, and `clear` accept these filters:

| Flag                 | Effect                                                      |
|----------------------|-------------------------------------------------------------|
| `--user &lt;account&gt;`   | Restrict to a single local account.                         |
| `--all-users`        | Apply to every local account.                               |
| `--appid &lt;id&gt;`       | Restrict to a single AppID (diff/apply only).               |
| `--force`            | Bypass the Steam-running check on writing commands.         |

`shortcuts edit` accepts `--user` and `--force` only (no `--all-users`,
no `--appid` — the shortcuts file is inherently per-account). Its editor is
`$EDITOR` if set, else `vi`/`nano`/`nvim` (in order) if on PATH; when none
is found it exits 2 with a clear message. `scopebuddy init` accepts
`--missing` (init every game lacking a stub) and `--force` (overwrite
existing stubs).

CLI flags override `[general] target_users` from `policies.toml`. `--user`
and `--all-users` are mutually exclusive.

## Exit codes

| Code | Meaning                                              |
|------|------------------------------------------------------|
| 0    | OK / no drift                                        |
| 1    | Drift detected or ScopeBuddy issues                  |
| 2    | Steam is running (write commands), or `config` on a non-interactive stream / conflicting `--tui` `--classic` |
| 3    | Invalid input / failed precondition: policy parse error, `--user` + `--all-users` together, missing `config get` key, unknown AppID or missing path (`open`), no matching account, `update` on a non-frozen install, aborted `shortcuts edit` |
| 4    | Write error: `apply` failed mid-write (the pre-apply checkpoint is kept — `restore --last` rolls back), or an `update` download/install failure |

Useful for scripting: `steam-manager diff && echo "clean" || echo "drift"`.

## Backups

Backups live at `~/.local/state/steam-manager/backups/&lt;ISO-ts&gt;.tar.gz`. Each
checkpoint is a single atomic archive containing:

```
manifest.json
config.vdf
users/&lt;account&gt;/localconfig.vdf
users/&lt;other-account&gt;/localconfig.vdf
```

`shortcuts edit` checkpoints hold `users/&lt;account&gt;/shortcuts.vdf` instead;
deleting an orphan config from the ScopeBuddy dashboard writes a `scb-delete`
checkpoint holding `scopebuddy/&lt;stem&gt;.conf`. `restore` maps every member kind
back to its live location — the ScopeBuddy member back to
`~/.config/scopebuddy/games/steam/&lt;stem&gt;.conf`.

Archives are written to a `.tmp` file first, then `rename(2)` into place —
no partial-checkpoint states are possible. Auto-pruned to the most recent
`[general] max_backups` archives.

`restore` reads the manifest, replays only the files actually present in the
chosen archive, and skips users that no longer exist locally.

For the `manifest.json` field-by-field schema and atomicity details, see
[`ARCHITECTURE.md § Backup format`](ARCHITECTURE.md#5-backup-format).

## Safety rails

- `apply`, `restore`, `clear`, and `shortcuts edit` refuse to run when Steam
  is running (detected via `~/.steam/steam.pid`). Use `--force` (or the env
  var `STEAM_MANAGER_FORCE=1`) to override.
- `apply` and `clear` always create a checkpoint before writing — no opt-out.

## Terminal compatibility

Tables emit OSC 8 hyperlinks: the AppID cell links to the Proton compatdata
folder, the Name cell links to the install folder, and orphan ScopeBuddy
config paths link to the `.conf` file. Paths are URL-encoded so names with
spaces work.

| Terminal                                  | OSC 8 support                                                                                 |
|-------------------------------------------|-----------------------------------------------------------------------------------------------|
| Ptyxis, Kitty, WezTerm, Alacritty, iTerm2 | Clickable out of the box                                                                       |
| GNOME Terminal                            | Ctrl+Click                                                                                     |
| Konsole                                   | Requires `file://` in *Settings > Profile > Allowed Link Schemes* (whitelist), then Ctrl+Click |

If your terminal does not support OSC 8, use `steam-manager open &lt;appid&gt;`
instead — it shells out to `xdg-open`.

Tables size to their content and grow only as wide as they need, up to the
terminal width — they never truncate a column while horizontal space is free,
and never stretch with empty gaps on an ultrawide terminal. A terminal
narrower than the content ellipsis-truncates the launch-option columns. `--help`
text is capped at a fixed readable width regardless of terminal size.

Visual conventions in `list`:

- **Bold** row → the app's current state drifts from the policy and will be
  changed by `apply`.
- **Dim** row → the app already conforms (or no policy applies).

The `NO_COLOR=1` environment variable disables all color and emphasis (rich
honors the [NO_COLOR](https://no-color.org/) standard); table box characters
remain.

## Environment variables

| Variable                       | Effect                                                                  |
|--------------------------------|-------------------------------------------------------------------------|
| `STEAM_MANAGER_STEAM_ROOT`     | Override the auto-detected Steam root.                                  |
| `STEAM_MANAGER_POLICY_PATHS`   | Colon-separated list of TOML policy files (replaces user override).     |
| `STEAM_MANAGER_BACKUP_ROOT`    | Override the default backup directory.                                  |
| `STEAM_MANAGER_SCB_DIR`        | Override the ScopeBuddy configs dir (`~/.config/scopebuddy/games/steam/`). |
| `STEAM_MANAGER_COMPAT_DIRS`    | Colon-separated list of system-wide `compatibilitytools.d/` dirs (replaces the built-in `/usr/share/steam` + `/usr/local/share/steam` paths). |
| `STEAM_MANAGER_FORCE=1`        | Equivalent to passing `--force` (bypasses the Steam-running check).     |
| `STEAM_MANAGER_INSTALL_DIR`    | Used by `scripts/install.sh` to override the default `~/.local/bin`.    |
| `STEAM_MANAGER_VERSION`        | Used by `scripts/install.sh` to pin to a specific release tag.          |
| `STEAM_MANAGER_USER_POLICY`    | Override the path written by `config set`/`unset` and the wizard.       |
| `STEAM_MANAGER_CONFIG_UI`      | Pick the `config` editor front-end: `tui` or `classic`. A `--tui`/`--classic` flag overrides it; an unrecognized value is ignored. |
| `STEAM_MANAGER_SCB_UI`         | Pick the bare `scopebuddy` front-end: `tui` (dashboard) or `observe` (report). Overrides the terminal-interactivity default; an unrecognized value is ignored. |
| `STEAM_MANAGER_NO_UPDATE_NOTIFIER` | Silence the post-command "new release available" hint (any value).  |
| `STEAM_MANAGER_UPDATE_REPO`    | Override the GitHub repo (`MatrixDJ96/steam-manager`) for `update`.     |
| `STEAM_MANAGER_UPDATE_STATE`   | Override the notifier's cache file path (testing convenience).          |
| `STEAM_MANAGER_QUIET=1`        | Read by `scripts/install.sh`: silence the PATH banner + "try it" line. Set by `steam-manager update` so the installer's output stays focused on download/verify/install. |
| `CI`                           | When set (any value), suppresses the update notifier.                   |
| `EDITOR`                       | Editor command used by `shortcuts edit` (fallback: `vi`/`nano`/`nvim`).                 |
| `NO_COLOR=1`                   | Disable colors and bold/dim emphasis (rich honors the standard).        |
