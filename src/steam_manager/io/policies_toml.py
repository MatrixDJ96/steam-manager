"""Read/write of the user `policies.toml` file (`~/.config/steam-manager/`).

`tomlkit` (not stdlib `tomllib`) is used because writes must preserve user
comments. The bundled factory `policies.toml` ships inside the package and
is read read-only via `importlib.resources` so it works equally in editable
installs, wheels, and the PyInstaller `_MEIPASS` bundle.

User override path can be overridden via STEAM_MANAGER_USER_POLICY (used
by tests). The CLI-side helper `cli/_common.py` re-exports USER_POLICY_PATH.
"""
from __future__ import annotations

import os
import tomllib
from importlib.resources import files
from pathlib import Path

import tomlkit

DEFAULT_USER_POLICY_PATH = Path.home() / ".config" / "steam-manager" / "policies.toml"


def user_path() -> Path:
    """Resolve the user policy file path, honoring STEAM_MANAGER_USER_POLICY."""
    override = os.environ.get("STEAM_MANAGER_USER_POLICY")
    return Path(override) if override else DEFAULT_USER_POLICY_PATH


def load_doc() -> tomlkit.TOMLDocument:
    """Read and parse the user policy file. Returns an empty document if absent."""
    path = user_path()
    if not path.exists():
        return tomlkit.document()
    return tomlkit.parse(path.read_text())


def save_doc(doc: tomlkit.TOMLDocument) -> None:
    """Atomic write: tmp file + os.replace. Creates parent dir if needed."""
    path = user_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(tomlkit.dumps(doc))
    os.replace(tmp, path)


def validate_toml(text: str) -> Exception | None:
    """Return the parse error if `text` is not valid TOML, else None."""
    try:
        tomllib.loads(text)
        return None
    except tomllib.TOMLDecodeError as exc:
        return exc


def render_initial_template() -> str:
    """Produce a seed file for the user policy: the bundled factory,
    fully commented out.

    The user file is a deep-merge override on top of the factory. Showing
    the factory pre-commented lets the user uncomment only what they want
    to override; lines left commented continue to track future factory
    updates automatically.
    """
    factory_text = files("steam_manager").joinpath("policies.toml").read_text()
    header = (
        "# steam-manager user policy\n"
        "#\n"
        "# Deep-merged on top of the factory policies.toml bundled with the package.\n"
        "# Below are the factory defaults, pre-commented. Uncomment only what you\n"
        "# want to override; the rest stays at the factory value (and tracks any\n"
        "# future updates to it).\n"
        "#\n"
        "# Run `steam-manager config show` to inspect the effective config.\n\n"
    )
    out = []
    for line in factory_text.splitlines():
        if not line.strip():
            out.append("")
        elif line.lstrip().startswith("#"):
            out.append(line)
        else:
            out.append(f"# {line}")
    return header + "\n".join(out) + "\n"
