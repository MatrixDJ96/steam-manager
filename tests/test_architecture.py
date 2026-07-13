"""Architectural rules — enforced via AST inspection of every module.

The package is split into layers (see AGENTS.md "Architecture"):

  cli/    can import: io/, policy, safety, render, models, __init__
  io/     can import: models  (and stdlib + vdf + tomlkit + tomllib)
  policy  can import: models
  render  can import: nothing from the project (pure Rich)
  safety  can import: nothing from the project (pure stdlib)
  models  can import: nothing from the project (pure stdlib)

If you intentionally need to relax these rules (e.g. you decide
render.py can import models, which is fine), update this test along
with the decision. Don't silently bend the layering by adding an
import the test would have flagged.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "steam_manager"


def _project_imports(file_path: Path) -> set[str]:
    """Return the set of `steam_manager.*` modules imported by file_path.

    Both `import steam_manager.X` and `from steam_manager.X import Y`
    are captured. Returns top-level subpackage names only (e.g. 'io',
    'cli', 'policy'), not the full dotted path.
    """
    tree = ast.parse(file_path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("steam_manager."):
                    out.add(alias.name.split(".")[1])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("steam_manager"):
                parts = node.module.split(".")
                if len(parts) >= 2:
                    out.add(parts[1])
                # `from steam_manager import X` → X is the imported package name
                if node.module == "steam_manager":
                    for alias in node.names:
                        out.add(alias.name)
    return out


def _glob_layer(layer: str) -> list[Path]:
    """All .py files under src/steam_manager/<layer>/, recursively."""
    base = SRC / layer
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


# --- io/ layer must not import from cli/, render, policy -------------------

FORBIDDEN_IN_IO = {"cli", "render", "policy", "safety"}


def test_io_layer_does_not_import_upper_layers():
    """io/ is pure data: never reaches up into CLI, rendering, or policy."""
    violators: dict[str, set[str]] = {}
    for f in _glob_layer("io"):
        imports = _project_imports(f)
        bad = imports & FORBIDDEN_IN_IO
        if bad:
            violators[str(f.relative_to(SRC))] = bad
    assert not violators, (
        f"io/ layer reached upward into forbidden modules: {violators}"
    )


# --- policy must not import from io or cli ---------------------------------

def test_policy_does_not_import_cli_or_io():
    """policy.py is pure logic over data classes; no file I/O, no Typer."""
    imports = _project_imports(SRC / "policy.py")
    assert "cli" not in imports, "policy.py must not import from cli/"
    assert "io" not in imports, "policy.py must not import from io/"
    assert "render" not in imports, "policy.py must not import from render"


# --- render must not import any project module ------------------------------

def test_render_has_no_project_deps():
    """render.py is pure Rich + Questionary. Nothing else from the project."""
    imports = _project_imports(SRC / "render.py")
    # Only models is acceptable in principle, but currently render uses none.
    assert imports == set() or imports <= {"models"}, (
        f"render.py reached into the project: {imports}"
    )


# --- safety.py only does the pid-file probe --------------------------------

def test_safety_minimal_deps():
    """safety.py: steam_running() only. No CLI, no render, no policy, no io."""
    imports = _project_imports(SRC / "safety.py")
    bad = imports & {"cli", "render", "policy", "io"}
    assert not bad, f"safety.py reached into forbidden modules: {bad}"


# --- models.py is dependency-free -----------------------------------------

def test_models_is_dependency_free():
    """models.py: dataclasses only. No project imports."""
    imports = _project_imports(SRC / "models.py")
    assert imports == set(), f"models.py must not import anything project-level: {imports}"


# --- cli/ may not reach underscore-private names from io/ -------------------

def _project_from_imports(file_path: Path) -> list[tuple[str, str]]:
    """Return list of (module, name) for every `from steam_manager.X import Y`
    in `file_path`. Catches private-leak imports like
    `from steam_manager.io.config_vdf import _load_compat_map`."""
    tree = ast.parse(file_path.read_text())
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("steam_manager"):
                for alias in node.names:
                    out.append((node.module, alias.name))
    return out


def test_cli_does_not_import_io_privates():
    """cli/ must consume io/ only through its public API. Reaching for a
    `_`-prefixed io/ name signals a leaked private (the original
    `steam._load_compat_map` smell that the audit caught) and a layering
    boundary worth re-stating instead of papering over."""
    allowed_private = {"_vdf_util"}  # the only documented `_`-name in io/
    violations: list[tuple[str, str, str]] = []
    for f in _glob_layer("cli"):
        for module, name in _project_from_imports(f):
            if not module.startswith("steam_manager.io"):
                continue
            # Strip module prefix to get the last segment (e.g. "io.compat_tools").
            if name.startswith("_") and name not in allowed_private:
                violations.append((str(f.relative_to(SRC)), module, name))
    assert not violations, (
        "cli/ imported private io/ symbols (leaked-private antipattern): "
        + ", ".join(f"{f}: {m}.{n}" for f, m, n in violations)
    )


# --- textual is confined to cli/tui/ ---------------------------------------

_TUI_DIR = SRC / "cli" / "tui"


def _imports_textual(file_path: Path) -> bool:
    tree = ast.parse(file_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "textual" or a.name.startswith("textual.")
                   for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "textual"
                                or node.module.startswith("textual.")):
                return True
    return False


def test_textual_confined_to_cli_tui():
    """Textual may be imported ONLY under cli/tui/. Keeping it out of every
    other module is what lets `--version`, `list`, and `config get` run without
    loading a heavy TUI toolkit, and keeps the non-TTY/headless path cheap."""
    violators = [
        str(f.relative_to(SRC))
        for f in SRC.rglob("*.py")
        if "__pycache__" not in f.parts
        and _TUI_DIR not in f.parents
        and _imports_textual(f)
    ]
    assert not violators, f"textual imported outside cli/tui/: {violators}"


def test_wizard_core_stays_render_free():
    """cli/_wizard_core.py is the pure decision core shared by the classic
    wizard and the TUI: it imports none of the render-coupled modules
    (_drift/_targets/render) and no UI toolkit (questionary/textual), so the
    edit logic stays unit-testable without a terminal."""
    tree = ast.parse((SRC / "cli" / "_wizard_core.py").read_text())
    forbidden = {"questionary", "textual"}
    forbidden_project = {"steam_manager.render", "steam_manager.cli._drift",
                         "steam_manager.cli._targets"}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations += [a.name for a in node.names
                           if a.name.split(".")[0] in forbidden
                           or a.name in forbidden_project]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden or node.module in forbidden_project:
                violations.append(node.module)
            if node.module in {"steam_manager", "steam_manager.cli"}:
                violations += [a.name for a in node.names
                               if a.name in {"render", "_drift", "_targets"}]
    assert not violations, f"_wizard_core.py imported render-coupled modules: {violations}"


def test_scb_core_stays_render_free():
    """cli/_scb_core.py is the pure decision core for the ScopeBuddy dashboard:
    it imports none of the render-coupled modules (_drift/_targets/render) and
    no UI toolkit (questionary/textual), so the classification logic stays
    unit-testable without a terminal."""
    tree = ast.parse((SRC / "cli" / "_scb_core.py").read_text())
    forbidden = {"questionary", "textual"}
    forbidden_project = {"steam_manager.render", "steam_manager.cli._drift",
                         "steam_manager.cli._targets"}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations += [a.name for a in node.names
                           if a.name.split(".")[0] in forbidden
                           or a.name in forbidden_project]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden or node.module in forbidden_project:
                violations.append(node.module)
            if node.module in {"steam_manager", "steam_manager.cli"}:
                violations += [a.name for a in node.names
                               if a.name in {"render", "_drift", "_targets"}]
    assert not violations, f"_scb_core.py imported render-coupled modules: {violations}"


def test_cli_tui_not_imported_at_module_scope_elsewhere():
    """Nothing outside cli/tui/ may import cli.tui at MODULE scope — the
    dispatcher imports it lazily inside a function, so non-TUI commands never
    drag Textual in at startup."""
    violators: list[str] = []
    for f in SRC.rglob("*.py"):
        if "__pycache__" in f.parts or _TUI_DIR in f.parents:
            continue
        for node in ast.parse(f.read_text()).body:  # module scope only
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
                if node.module == "steam_manager.cli":
                    mods += [f"steam_manager.cli.{a.name}" for a in node.names]
            if any(m == "steam_manager.cli.tui" or m.startswith("steam_manager.cli.tui.")
                   for m in mods):
                violators.append(str(f.relative_to(SRC)))
    assert not violators, (
        f"cli.tui imported at module scope outside cli/tui/: {violators}"
    )
