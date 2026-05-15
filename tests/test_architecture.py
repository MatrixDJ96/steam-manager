"""Architectural rules — enforced via AST inspection of every module.

The package is split into layers (see CLAUDE.md "Architecture"):

  cli/    can import: io/, policy, safety, render, models, __init__
  io/     can import: models  (and stdlib + vdf + tomlkit + tomllib)
  policy  can import: models
  render  can import: nothing from the project (pure Rich)
  safety  can import: nothing from the project (pure stdlib)
  models  can import: nothing from the project (pure stdlib)
  steam   shim re-export — allowed to import from io/ + models

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


# --- safety.py only depends on io.backups (re-export shim) -----------------

def test_safety_minimal_deps():
    """safety.py: steam_running() plus a backwards-compat re-export of
    io.backups.* . No CLI, no render, no policy."""
    imports = _project_imports(SRC / "safety.py")
    bad = imports & {"cli", "render", "policy"}
    assert not bad, f"safety.py reached into forbidden modules: {bad}"


# --- models.py is dependency-free -----------------------------------------

def test_models_is_dependency_free():
    """models.py: dataclasses only. No project imports."""
    imports = _project_imports(SRC / "models.py")
    assert imports == set(), f"models.py must not import anything project-level: {imports}"
