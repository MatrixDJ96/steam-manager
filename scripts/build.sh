#!/usr/bin/env bash
# Build a single-file Linux binary of steam-manager via PyInstaller.
set -euo pipefail

# Resolve repo root (parent of this script's dir)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
cd "${REPO_ROOT}"

# Activate venv if not already active
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# Ensure pyinstaller is installed
if ! command -v pyinstaller >/dev/null 2>&1; then
    pip install ".[build]"
fi

# Clean previous build artifacts
rm -rf build dist steam-manager.spec

pyinstaller \
    --onefile \
    --name steam-manager \
    --clean \
    --collect-data steam_manager \
    --collect-submodules rich_click \
    --hidden-import vdf \
    --hidden-import questionary \
    --hidden-import tomlkit \
    src/steam_manager/__main__.py

# Emit a SHA256 checksum alongside the binary so the installer can verify it.
( cd dist && sha256sum steam-manager > steam-manager.sha256 )

echo
echo "Built: $(realpath dist/steam-manager)"
echo "Size: $(du -h dist/steam-manager | cut -f1)"
echo "SHA256: $(cut -d' ' -f1 dist/steam-manager.sha256)"
echo "Run: ./dist/steam-manager --version"
