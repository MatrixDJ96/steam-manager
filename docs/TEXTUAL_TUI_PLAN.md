# Textual TUI redesign of `steam-manager config` — implementation plan

> **Generated autonomously** (multi-agent design workflow: probe → architect → red-team → finalize, 9 agents). Owner approved the *direction* (Textual TUI) on 2026-06-02; this is the phased plan, red-teamed, that the autonomous implementation follows on the `develop` branch.

**Headline:** Replace the questionary wizard with a full-screen Textual TUI on a *verified-pure* shared core, flag-gated through a 4-phase rollout. Two blockers (DataTable column semantics, "Apply" verb collision) are resolved by design, not docs; the core is made genuinely render-free by keeping drift out of it.

---

## Architecture

Replace the questionary `config wizard` with a full-screen Textual TUI sitting on a **shared, genuinely-pure core**. Both the TUI and the surviving classic flow drive the same read boundary (`load_state`), write boundary (`apply`), and pure `set_*` reducers. `io/`, `policy.py`, `render.py`, `safety.py`, `models.py` stay byte-for-byte untouched. The scriptable `config get/set/unset/path` verbs and their exit codes are never touched.

### Critical correction to the core's import graph (red-team HIGH, verified)

`_targets.py` does `from steam_manager import render`, and `render.py` does `import questionary` (+ `prompt_toolkit`). `_drift.py` imports `_targets`. So importing `_drift` or `_targets` into `_wizard_core.py` would drag questionary/prompt_toolkit/typer in at import time and **break the "pure core" property the whole test strategy leans on.** Resolution:

- `cli/_wizard_core.py` imports **only**: `policy`, `io.policies_toml`, `io.discovery`, `io.compat_tools` (public names), `_appinfo`, `_common`. It does **NOT** import `_drift` or `_targets`.
- **Drift is computed in the UI layer, never in the core.** `load_state` does not compute `drift_count`. The TUI (`cli/tui/app.py`) computes drift in a background worker after mount via `_drift.compute_drift`; the classic flow ignores it. `WizardData` drops the `drift_count` field.
- For `general.target_users` the core needs no `_targets`: it stores/reads the raw spec list (`["active"] | ["*"] | explicit names`) and folds a `Change`; mapping a spec to actual `SteamUser` objects (the render-coupled part) is never needed by the core. Account-name pickers use `state.data.users` directly.

This makes "Phase 1 adds no questionary-tainted import; no Textual anywhere" actually true.

### GameRow column semantics (red-team BLOCKER, verified)

`list`/`_list_render.py` populate Compat/Launch from **on-disk** Steam VDF (`config_vdf.get_compat_tool` / `localconfig_vdf.get_launch_options`). The TUI must not show an identical-looking grid that secretly means "policy intent." Resolution (Option A, dual-column):

- The DataTable has columns **Name / AppID / Policy Compat / Policy Launch / On-disk** (the on-disk cell shows compat+launch or a `=` when policy matches disk). The Policy columns are editable (resolved via `policy.resolve` over the loaded engine in `load_state`). The On-disk columns are read live (best-effort) and rendered dim.
- Rows where Policy != disk get the **same bold/drift marker `list` already uses**, so the config→apply gap is visible per game, not just as one aggregate line. The aggregate drift line stays as a header subtitle.

### "Apply" verb collision (red-team HIGH/BLOCKER, verified)

`steam-manager apply` means "write Steam VDF + auto-backup + Steam-closed guard." The TUI's commit only writes `policies.toml`. Resolution:

- The TUI's commit verb is **"Save"** everywhere: footer `s save`, success toast **"Saved policy. Run `steam-manager apply` to write Steam."** The word "Apply" is reserved product-wide for the Steam-writing command.
- After Save, recompute and keep the drift line on-screen so the next step is always visible.

### SSH / headless / degraded-terminal hardening (red-team HIGH)

`isatty()==True` over SSH/tmux/mosh, so the non-TTY guard does NOT fire there — the App spins up and must be usable:

- `_dispatch_config_ui` gates on `_ui_is_interactive()` (stdin AND stdout `isatty()`, mirroring `_update_check._is_stderr_tty`'s try/except) **before importing tui**. On non-TTY: stderr hint listing `config get/set/unset/path` + `$EDITOR "$(steam-manager config path)"`, then `typer.Exit(2)`.
- The `tui.run()` call is wrapped: any Textual startup exception (bad `$TERM`/terminfo, driver failure) is caught and falls through to the **same scriptable hint + exit 2** — never a raw traceback or a wedged raw-mode terminal.
- **Every clickable affordance is key-reachable.** Defaults bar cards get explicit bindings; a Pilot test asserts each editable region is reachable with no mouse.
- ASCII fallback for marker glyphs (✓✗⚠←·) gated on locale/encoding; a Pilot/CI case runs under `LANG=C`.
- A small-terminal Pilot case (80×24) asserts the layout degrades to a usable single column rather than clipping the Pending pane off-screen.

### Drift never blocks the editor (red-team MEDIUM)

- The background drift worker catches `(FileNotFoundError, OSError, Exception)` and sets the drift line to "drift unavailable" — it is decorative and never blocks the initial paint.
- `load_state` itself degrades when `discovery.discover()` raises `FileNotFoundError`: the TUI shows a graceful "No Steam install found — editing policy only" banner, not a stack trace. Policy editing still works.

### Empty-state parity (red-team MEDIUM)

- Empty games table → centered "No installed games found."
- Empty compat PickerScreen → "No compat tools found in compatibilitytools.d/."
- Zero users in TargetUsersScreen → "No Steam accounts found," multiselect disabled.
- A Pilot test on a zero-games/zero-tools fake_steam variant asserts the message renders.

### Validation lives in the pure core (red-team MEDIUM)

A Textual `Input` is a string widget. `set_max_backups` (pure core) owns coercion: accept the raw string, strip, `int()`, reject `< 1` by returning state unchanged — mirroring `prompt_int`. `set_launch_options` preserves the empty-string → `_UNSET` clear behavior. Reducer unit tests cover `''`, `'abc'`, `'0'`, `'08'`. Keeping this in the core keeps it in the fast, no-asyncio lane.

## File layout

- `cli/_wizard_core.py` (NEW) — pure core. Relocates `Change`, `_UNSET`, `_merge_pending`, `_is_noop`, `_apply_changes`, `_effective`, `_toml_array`, `_appids_with_ignore`, `_read_ignored_from_user_doc`, `_installed_games` verbatim. Adds `GameRow`, `WizardData` (no `drift_count`), `WizardState`; `load_state`, `apply`, `set_compat_tool`, `set_launch_options`, `set_target_users`, `set_max_backups`, `set_ignored`, `toggle_ignore`, `discard`, `can_reset`, `reset`, `effective_value`. Imports policy/policies_toml/discovery/compat_tools/_appinfo/_common only.
- `cli/_wizard.py` (CHANGED) — re-imports the relocated symbols from `_wizard_core`; `run()` and `_flow_*` keep working as the classic entry. Stays the symbol the classic dispatch test patches.
- `cli/_config_entry.py` (NEW) — `_ui_is_interactive()`, `_resolve_mode(classic, tui)` (flag > env > default), `_dispatch_config_ui(...)` with the non-TTY guard + `tui.run()` exception wrapper, `_non_tty_hint()`.
- `cli/_common.py` (CHANGED) — add `config_ui_mode()` reading `STEAM_MANAGER_CONFIG_UI` (unrecognized → None). ExitCode unchanged; exit 2 is free in the config namespace (config never runs the Steam guard).
- `cli/config_cmd.py` (CHANGED) — `config_callback` + `wizard()` delegate to `_dispatch_config_ui`; add mutually-exclusive `--classic/--no-classic` + `--tui/--no-tui` to both. `get/set_/path/unset` byte-for-byte. **No module-level `import textual`** — tui imported lazily inside `_dispatch_config_ui` only.
- `cli/tui/` (NEW, the only place textual is imported): `__init__.py` (`run(ctx_or_none) -> int`), `app.py` (`ConfigApp(App)`, BINDINGS, compose, reactive `WizardState`, `watch_state`, async drift worker, inline CSS via `importlib.resources` — **NOT `CSS_PATH`/`__file__`**), `widgets.py` (CompatPickerScreen, LaunchPickerScreen, TargetUsersScreen, max_backups Input, ConfirmScreen), `app.tcss` (package data).

## Deps (pyproject.toml)

- ADD `"textual >= 8.2, < 9"` (latest 8.2.7; `<9` caps next major, matching click/typer/rich-click discipline).
- CHANGE `"rich >= 13"` → `"rich >= 14.2"` (textual 8.2.7 `Requires-Dist: rich>=14.2.0`). The live venv already runs rich 15 + rich-click 1.9.8 with the `_rich.py` `__class__` swap intact, so the floor is empirically safe.
- Do NOT touch click/typer/rich-click — textual's Requires-Dist contains none of them. Do NOT install `textual[syntax]` (tree-sitter, tens of MB, unused).
- ADD `"pytest-asyncio"` to `[project.optional-dependencies].dev`.
- `[tool.pytest.ini_options]`: register `markers = ["tui: Textual Pilot interaction tests (slow lane)"]` and `asyncio_mode = "auto"`. Document `pytest -m 'not tui'` as the local sub-2s lane.

## Build (scripts/build.sh)

Add to the pyinstaller invocation: `--collect-submodules textual` (defeats the lazy-widget `__getattr__` `_MEIPASS` trap) **and `--hidden-import platformdirs`** (imported at App construction — add now, not verify-then-add). `app.tcss` rides the wheel via existing `--collect-data steam_manager`. Mandatory: open the TUI in a real terminal against the **frozen** binary — pytest runs the editable install and cannot catch the lazy-import crash.

## Tests

Two lanes. **FAST** (sub-2s, no asyncio, no textual import): the 9 scriptable `test_config_cli.py` tests byte-for-byte; `test_wizard_core.py` (load_state, every reducer, revert-drops-entry, validation rejections, apply-writes-once); retargeted pure-seam suites in `test_config_wizard.py`; `test_config_entry.py` (dispatch ladder, non-TTY exit 2 + four primitive names in stderr + neither run called, flag>env>default precedence). The App-construction smoke is **marked `tui`**.

**SLOW** (`@pytest.mark.tui`, pytest-asyncio, `tests/test_tui.py`): Pilot tests via `app.run_test()` — DataTable lists the 2 fake games, type-to-filter, edit stages a Change into Pending(N), Space ignores, Save writes `policies.toml` exactly once and clears, quit-with-pending confirms+discards without writing, plus hardening cases: every editable region key-reachable, `LANG=C` glyph fallback, 80×24 layout, empty-state messages.

`test_config_wizard.py` triage into three buckets: (1) pure-seam → retarget import (mechanical); (2) `_flow_*` Change-assertions → migrate to `test_wizard_core.py`; (3) `_pick_area`/run-loop/breadcrumb tests (classic-only questionary plumbing, no core equivalent) → STAY against `_wizard` until the classic flow is deleted.

`tests/test_architecture.py`: the 9 scriptable tests stay byte-for-byte; the 2 dispatch tests are EXPECTED to change. **In Phase 2's first commit** add the textual-confinement guard: walk `src/steam_manager/**/*.py`, parse imports, assert any module importing a `textual`-prefixed name resolves to a path **under `cli/tui/`** — strict, no "or at least cli/" escape clause. Additionally assert nothing outside `cli/tui/` imports `cli.tui` at module scope.

## Dispatch test fix (pinned now)

`test_config_no_subcommand_launches_wizard` and `test_config_wizard_explicit_launches_wizard` patch `_wizard.run` with no isatty forcing; CliRunner's StringIO `isatty()==False`, so the guard would flip them to exit 2. Fix **in the same commit as the guard, Phase 2**: rewrite both to invoke **with `--classic`** + monkeypatch `_config_entry._ui_is_interactive -> True`, asserting the classic path forever. Add ONE new test asserting the bare/default interactive path routes to the `tui.run` symbol. Phase 3 then only flips a constant.

## Rollout

Precedence: explicit flag (`--classic`/`--tui`, both → exit 2) > `STEAM_MANAGER_CONFIG_UI=tui|classic` (unrecognized ignored) > built-in default. Phase 2 ships default `classic` (TUI opt-in). Phase 3 flips default to `tui`; `--classic` is the documented escape hatch for one release. Phase 4 documents everything and records a **dated trigger** to delete `_wizard.py` + `--classic` + orphaned `render.py` questionary prompts (grep first — restore/shortcuts/scopebuddy still use `render.confirm`/`select_*`) in the release after the flip.

---

## Phase summary

| Phase | Effort | Ships |
|------|:------:|-------|
| **1 — Extract the pure core** (`cli/_wizard_core.py`); classic flow delegates to it. Drift kept OUT of the core. Zero behaviour change. | M | A genuinely-pure, immutable, fully unit-tested core for all config edits; the classic wizard runs on it unchanged; all existing tests green; no textual anywhere yet. |
| **2 — Textual TUI behind `--tui`/env** (default still classic). New `cli/tui/` package, dispatcher + non-TTY guard + `run()` exception wrapper, packaging, dual-column DataTable, 'Save' verb, async drift, empty-states, degradation hardening. Confinement guard + dispatch-test fix land in the FIRST commit. | XL | The full TUI usable end-to-end via flag/env, SSH/tmux/LANG=C/80×24-hardened, with the safe classic default still in place and the frozen binary proven to launch it. |
| **3 — Flip the built-in default to `tui`**; `--classic` stays the escape hatch. | S | Bare `steam-manager config` opens the TUI by default; classic reachable via one flag; non-TTY still degrades to hint+exit 2. One-constant change touching no test intent. |
| **4 — Docs** across REFERENCE/HOWTO/ARCHITECTURE/README/AGENTS; measured binary size; dated classic-flow deletion trigger. | M | The new UX fully documented and discoverable, the layering decision enforced (not conventional), and the second code path scheduled for removal so it can't ossify. |

## First commit (the safe down-payment)

Phase 1, commit 1: create `src/steam_manager/cli/_wizard_core.py` and RELOCATE verbatim from `_wizard.py` the already-pure, UI-free symbols — `Change`, `_UNSET`, `_merge_pending`, `_is_noop`, `_apply_changes`, `_effective`, `_toml_array`, `_appids_with_ignore`, `_read_ignored_from_user_doc`, `_installed_games` — then in `_wizard.py` replace those definitions with `from steam_manager.cli._wizard_core import (...)`. Run `pytest` (all green, zero behaviour change) and `pytest tests/test_architecture.py` (all 6 green). Reversible; de-risks everything after.

## Open questions — decisions taken autonomously (AUTO mode)

The owner granted full autonomy, so these red-team open questions are resolved as follows (revisit on review):

1. **DataTable On-disk column.** The approved mockup showed a single Compat/Launch pair; the red-team recommends dual Policy + On-disk columns. **Decision:** start with **Policy Compat / Policy Launch columns + per-row drift markers + the aggregate drift line** (closest to the mockup, readable at 80 cols); the dim On-disk column is a fast-follow enhancement once the layout is proven. Documented so it can be upgraded to full Option A on request.
2. **Forced `--tui` in a non-TTY.** **Decision:** hard-error (exit 2) — a script explicitly asking for a TUI in a pipe is a bug worth surfacing.
3. **Classic-flow deletion schedule.** **Decision:** dated trigger one release after Phase 3 ships as default (the escape-hatch bake window); recorded in Phase 4, not executed now.
4. **CI `tui` lane.** **Decision:** run `@pytest.mark.tui` in CI by default across the 3.11/3.12/3.13 matrix; `pytest -m 'not tui'` documented as the local sub-2s lane.
