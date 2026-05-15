"""`steam-manager config` sub-command: edit and inspect the user policy file."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import tomlkit
import typer

from steam_manager.cli._editor import choose_editor
from steam_manager.io import policies_toml

# Backward-compat aliases for tests that import private symbols from this
# module. These will be cleaned up when test_config_cli.py is updated to
# import from io/policies_toml.py directly.
_render_initial_template = policies_toml.render_initial_template
_user_path = policies_toml.user_path
_load_doc = policies_toml.load_doc
_save_doc = policies_toml.save_doc
_validate_toml = policies_toml.validate_toml

config_app = typer.Typer(help="Edit and inspect the user policy file.")


def _split_key(key: str) -> list[str]:
    parts = [p for p in key.split(".") if p]
    if not parts:
        raise typer.BadParameter(f"empty key: {key!r}")
    return parts


def _infer_value(raw: str) -> Any:
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    return raw


def _navigate(doc: tomlkit.TOMLDocument, parts: list[str], *, create: bool):
    """Walk dotted path. Returns (parent_table, leaf_key) or raises KeyError."""
    node: Any = doc
    for part in parts[:-1]:
        if part in node:
            node = node[part]
            if not isinstance(node, tomlkit.items.Table) and not isinstance(node, dict):
                raise typer.BadParameter(
                    f"cannot descend into non-table at '{part}' (got {type(node).__name__})"
                )
        elif create:
            node[part] = tomlkit.table()
            node = node[part]
        else:
            raise KeyError(part)
    return node, parts[-1]


@config_app.command()
def path() -> None:
    """Print the path of the user policy file."""
    typer.echo(str(_user_path()))


def _render_merged_doc() -> tomlkit.TOMLDocument:
    """Render the effective config — factory defaults plus user overrides.

    Used by `show` and `get` so both commands see the same source of truth.
    Honors STEAM_MANAGER_USER_POLICY exactly like every other config command.
    """
    from importlib.resources import files
    from steam_manager import policy
    factory = Path(str(files("steam_manager").joinpath("policies.toml")))
    override = os.environ.get("STEAM_MANAGER_POLICY_PATHS")
    if override:
        paths = [Path(p) for p in override.split(":") if p]
    else:
        paths = [factory, _user_path()]
    engine = policy.load(paths)
    out = tomlkit.document()
    out["general"] = tomlkit.table()
    out["general"]["max_backups"] = engine.max_backups
    out["general"]["target_users"] = engine.target_users
    for section_name, section in engine.sections.items():
        tbl = tomlkit.table()
        if section.compat_tool is not None:
            tbl["compat_tool"] = section.compat_tool
        if section.launch_options is not None:
            tbl["launch_options"] = section.launch_options
        out[section_name] = tbl
    if engine.overrides:
        ovr = tomlkit.table()
        for appid, fields in engine.overrides.items():
            ovr[appid] = fields
        out["overrides"] = ovr
    return out


@config_app.command()
def show() -> None:
    """Print the effective config (factory defaults plus your overrides)."""
    typer.echo(tomlkit.dumps(_render_merged_doc()).rstrip())


@config_app.command()
def edit() -> None:
    """Open the user policy file in $EDITOR. Loops on invalid TOML."""
    p = _user_path()
    file_existed_before = p.exists()
    if file_existed_before:
        initial_content = p.read_text()
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        initial_content = _render_initial_template()
        p.write_text(initial_content)

    editor = choose_editor()
    try:
        while True:
            subprocess.run([*editor, str(p)], check=False)
            text = p.read_text()
            err = _validate_toml(text)
            if err is None:
                # Strip any "# ERROR:" header we added in a prior iteration.
                lines = text.splitlines(keepends=True)
                stripped = []
                skipping = True
                for line in lines:
                    if skipping and (line.startswith("# ERROR:") or line.startswith("# Fix the file")):
                        continue
                    if skipping and line.strip() == "":
                        skipping = False
                        continue
                    skipping = False
                    stripped.append(line)
                cleaned = "".join(stripped)
                if cleaned != text:
                    p.write_text(cleaned)
                # No-op edit detection: if the content is unchanged from what
                # we started with (template seed for a new file, or the prior
                # contents for an existing file), don't claim "Saved". For a
                # newly-seeded file with no real edits, delete it — an absent
                # file is equivalent to the factory default.
                if cleaned == initial_content:
                    if not file_existed_before:
                        p.unlink()
                        typer.secho("No changes — file not created.", fg="yellow")
                    else:
                        typer.secho("No changes.", fg="yellow")
                else:
                    typer.secho(f"Saved {p}", fg="green")
                return
            typer.secho(f"TOML parse error: {err}", fg="red", err=True)
            header = (
                f"# ERROR: {err}\n"
                "# Fix the file and save again, or Ctrl-C to abort.\n\n"
            )
            p.write_text(header + text)
    except KeyboardInterrupt:
        typer.secho("Aborted; file may contain unsaved errors.", fg="yellow", err=True)
        raise typer.Exit(3)


@config_app.command()
def get(key: str) -> None:
    """Print the effective value at a dotted key (factory plus your overrides)."""
    parts = _split_key(key)
    doc = _render_merged_doc()
    try:
        parent, leaf = _navigate(doc, parts, create=False)
        value = parent[leaf]
    except KeyError:
        typer.secho(f"key not found: {key}", fg="red", err=True)
        raise typer.Exit(3)
    if isinstance(value, (tomlkit.items.Table, dict)):
        typer.echo(tomlkit.dumps({leaf: value}).rstrip())
    else:
        typer.echo(str(value))


@config_app.command(name="set")
def set_(key: str, value: str) -> None:
    """Set a dotted key. Type inference: true/false → bool, digits → int, else string."""
    parts = _split_key(key)
    doc = _load_doc()
    parent, leaf = _navigate(doc, parts, create=True)
    parent[leaf] = _infer_value(value)
    _save_doc(doc)
    typer.secho(f"Set {key} = {parent[leaf]!r}", fg="green")


@config_app.command()
def unset(key: str) -> None:
    """Remove a dotted key. Drops the parent table if it becomes empty."""
    parts = _split_key(key)
    doc = _load_doc()
    try:
        parent, leaf = _navigate(doc, parts, create=False)
        if leaf not in parent:
            raise KeyError(leaf)
    except KeyError:
        typer.secho(f"key not found: {key}", fg="red", err=True)
        raise typer.Exit(3)
    del parent[leaf]
    # Walk up and drop empty tables along the path.
    for i in range(len(parts) - 1, 0, -1):
        sub_parent, sub_leaf = _navigate(doc, parts[:i + 1], create=False) if False else (None, None)
        # Re-resolve from root since we may have just deleted something.
        node: Any = doc
        for part in parts[:i - 1]:
            node = node[part]
        candidate = node[parts[i - 1]]
        if isinstance(candidate, (tomlkit.items.Table, dict)) and len(candidate) == 0:
            del node[parts[i - 1]]
        else:
            break
    _save_doc(doc)
    typer.secho(f"Unset {key}", fg="green")


@config_app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Reset the user policy file to the commented factory template."""
    p = _user_path()
    if p.exists() and not yes:
        typer.confirm(
            f"Reset {p} to the factory template? This discards your overrides.",
            abort=True,
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render_initial_template())
    typer.secho(f"Reset {p}", fg="green")


@config_app.command()
def ignore(appid: str) -> None:
    """Add `[overrides.<appid>] ignore = true`. Validates that <appid> is numeric."""
    if not appid.isdigit():
        typer.secho(f"appid must be numeric, got: {appid}", fg="red", err=True)
        raise typer.Exit(3)
    doc = _load_doc()
    overrides = doc.setdefault("overrides", tomlkit.table())
    entry = overrides.setdefault(appid, tomlkit.table())
    entry["ignore"] = True
    _save_doc(doc)
    typer.secho(f"Ignored AppID {appid}", fg="green")
