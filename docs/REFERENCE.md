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
max_backups  = 20
# target_users — special values:
#   ["active"]      -> only the MostRecent=1 account in loginusers.vdf
#   ["matrixdj96"]  -> a specific account
#   ["*"]           -> every local account
#   ["a", "b"]      -> explicit list
target_users = ["active"]

[games]
# Applied to every app of type "game" or "beta".
compat_tool    = "Proton-CachyOS Latest"
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

| Command              | Description |
|----------------------|-------------|
| `list`               | List installed games with compat tool and per-user launch options. Drift rows are **bold**, conforming rows are **dim**. AppID and Name cells are clickable OSC 8 links. |
| `diff`               | Show planned changes vs policy (read-only). Exits 1 if drift exists. |
| `apply`              | Apply planned changes. Creates an auto-backup checkpoint; aborts if Steam is running (use `--force` to bypass). |
| `backup`             | Manually create a full checkpoint archive. |
| `restore`            | Restore from a previous checkpoint. Interactive single-select or `--last`. Aborts if Steam is running. |
| `open &lt;appid&gt;`       | Open the game's install folder (or `--compat` for compatdata) via `xdg-open`. |
| `clear`              | Wipe ALL compat tool overrides + launch options for every app (no type filter). Auto-backup. |
| `scopebuddy` / `scb` | ScopeBuddy: `observe` (default) + `init` (per AppID, `--missing`, interactive). `scb` is a short hidden alias. |
| `update`             | Self-update the binary to the latest GitHub release. `--check` (read-only), `--yes` (skip prompt), `--force` (reinstall same version). PyInstaller-only. |
| `shortcuts`          | Edit Steam's binary `shortcuts.vdf` (non-Steam games). `path`, `show`, `edit`. |

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
| `config path`                       | Print the user policy file path.                                                                        |
| `config show`                       | Print the effective config (factory + user, deep-merged). For the raw user file, use `cat $(steam-manager config path)`. |
| `config edit`                       | Open `$EDITOR` on the file (seeds with the commented factory if absent). Loops on invalid TOML — pattern `crontab -e`. If you exit without changes on a freshly-seeded file, no file is left on disk. |
| `config reset [--yes]`              | Reset the file to the commented factory template. Asks for confirmation unless `--yes` is passed.       |
| `config get <key>`                  | Print the value at a dotted key. Exit 3 if missing.                                                     |
| `config set <key> <value>`          | Set a dotted key. Type inference: `true`/`false` → bool, digits → int, else string.                     |
| `config unset <key>`                | Remove a dotted key. Drops the parent table if it becomes empty.                                        |
| `config ignore <appid>`             | Shortcut for `[overrides.<appid>] ignore = true`. Validates that `<appid>` is numeric.                  |

When the user file is created (via `edit` or `reset`), it is seeded with the bundled factory `policies.toml`, every line pre-commented. Uncomment only what you want to override; commented lines continue to track future factory updates.

Dotted keys: `games.compat_tool`, `general.max_backups`, `overrides.1495710.ignore`. Keys containing literal `.` are not supported.

Editor selection: `$EDITOR` if set, else `vi`/`nano`/`nvim` (in order) if on PATH. Sets exit 3 with a clear message if none is found.

### Shared user filters

`diff`, `apply`, `list`, `scopebuddy`, and `clear` accept these filters:

| Flag                 | Effect                                                      |
|----------------------|-------------------------------------------------------------|
| `--user &lt;account&gt;`   | Restrict to a single local account.                         |
| `--all-users`        | Apply to every local account.                               |
| `--appid &lt;id&gt;`       | Restrict to a single AppID (diff/apply only).               |
| `--force`            | Bypass the Steam-running check on writing commands.         |

CLI flags override `[general] target_users` from `policies.toml`. `--user`
and `--all-users` are mutually exclusive.

## Exit codes

| Code | Meaning                                              |
|------|------------------------------------------------------|
| 0    | OK / no drift                                        |
| 1    | Drift detected or ScopeBuddy issues                  |
| 2    | Steam is running, aborted                            |
| 3    | Config parse error or mutually-exclusive flags       |
| 4    | Write error (reserved for rollback path)             |

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

Archives are written to a `.tmp` file first, then `rename(2)` into place —
no partial-checkpoint states are possible. Auto-pruned to the most recent
`[general] max_backups` archives.

`restore` reads the manifest, replays only the files actually present in the
chosen archive, and skips users that no longer exist locally.

For the `manifest.json` field-by-field schema and atomicity details, see
[`ARCHITECTURE.md § Backup format`](ARCHITECTURE.md#5-backup-format).

## Safety rails

- `apply`, `restore`, and `clear` refuse to run when Steam is running
  (detected via `~/.steam/steam.pid`). Use `--force` (or the env var
  `STEAM_MANAGER_FORCE=1`) to override.
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
| `STEAM_MANAGER_FORCE=1`        | Equivalent to passing `--force` (bypasses the Steam-running check).     |
| `STEAM_MANAGER_INSTALL_DIR`    | Used by `scripts/install.sh` to override the default `~/.local/bin`.    |
| `STEAM_MANAGER_VERSION`        | Used by `scripts/install.sh` to pin to a specific release tag.          |
| `STEAM_MANAGER_USER_POLICY`    | Override the path written by `config edit`/`set`/`unset`/`ignore`.      |
| `STEAM_MANAGER_NO_UPDATE_NOTIFIER` | Silence the post-command "new release available" hint (any value).  |
| `STEAM_MANAGER_UPDATE_REPO`    | Override the GitHub repo (`MatrixDJ96/steam-manager`) for `update`.     |
| `STEAM_MANAGER_UPDATE_STATE`   | Override the notifier's cache file path (testing convenience).          |
| `STEAM_MANAGER_QUIET=1`        | Read by `scripts/install.sh`: silence the PATH banner + "try it" line. Set by `steam-manager update` so the installer's output stays focused on download/verify/install. |
| `CI`                           | When set (any value), suppresses the update notifier.                   |
| `EDITOR`                       | Editor command used by `config edit` / `shortcuts edit` (fallback: `vi`/`nano`/`nvim`). |
| `NO_COLOR=1`                   | Disable colors and bold/dim emphasis (rich honors the standard).        |
