#!/usr/bin/env bash
# steam-manager installer & updater.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh | bash
#   wget -qO- https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh | bash
#
# Re-running this script replaces the existing binary with the latest release.
#
# Environment variables:
#   STEAM_MANAGER_VERSION       release tag to install (default: latest)
#   STEAM_MANAGER_INSTALL_DIR   destination directory (default: $HOME/.local/bin)
#   STEAM_MANAGER_QUIET         when "1", silence the PATH banner + "try it"
#                               line (set by `steam-manager update` to keep
#                               the output focused on download/verify/install).

set -euo pipefail

REPO="MatrixDJ96/steam-manager"
ASSET="steam-manager"
VERSION="${STEAM_MANAGER_VERSION:-latest}"
INSTALL_DIR="${STEAM_MANAGER_INSTALL_DIR:-$HOME/.local/bin}"

if [ "$VERSION" = "latest" ]; then
    BINARY_URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"
    SHA256_URL="https://github.com/${REPO}/releases/latest/download/${ASSET}.sha256"
else
    BINARY_URL="https://github.com/${REPO}/releases/download/${VERSION}/${ASSET}"
    SHA256_URL="https://github.com/${REPO}/releases/download/${VERSION}/${ASSET}.sha256"
fi

if [ -t 1 ]; then
    BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

info() { printf '%s==>%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%swarn:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

# Preflight: Linux x86_64, plus curl or wget.
[ "$(uname -s)" = "Linux" ]   || die "Linux only (detected: $(uname -s))."
[ "$(uname -m)" = "x86_64" ]  || die "x86_64 only (detected: $(uname -m))."

if command -v curl >/dev/null 2>&1; then
    download() { curl -fsSL "$1" -o "$2"; }
    download_optional() { curl -fsSL "$1" -o "$2" 2>/dev/null; }
elif command -v wget >/dev/null 2>&1; then
    download() { wget -qO "$2" "$1"; }
    download_optional() { wget -qO "$2" "$1" 2>/dev/null; }
else
    die "need curl or wget."
fi

# Download to a tmpfile in the install dir, then atomic rename.
mkdir -p "$INSTALL_DIR"
TMP="$(mktemp "${INSTALL_DIR}/.steam-manager.XXXXXX")"
TMP_SHA="${TMP}.sha256"
trap 'rm -f "$TMP" "$TMP_SHA"' EXIT

info "downloading ${BOLD}${ASSET}${RESET} (${BOLD}${VERSION}${RESET}) → ${BOLD}${INSTALL_DIR}${RESET}"
download "$BINARY_URL" "$TMP" || die "download failed from $BINARY_URL"
[ -s "$TMP" ] || die "downloaded file is empty."

# Optional SHA256 verification: skip silently if the release lacks a .sha256
# (older releases) but warn the user.
if download_optional "$SHA256_URL" "$TMP_SHA" && [ -s "$TMP_SHA" ]; then
    expected="$(awk '{print $1}' "$TMP_SHA")"
    actual="$(sha256sum "$TMP" | awk '{print $1}')"
    if [ "$expected" != "$actual" ]; then
        die "SHA256 mismatch: expected $expected, got $actual."
    fi
    info "sha256 verified"
else
    warn "no .sha256 published for this release — skipping checksum verify."
fi

chmod +x "$TMP"
"$TMP" --version >/dev/null 2>&1 || die "binary failed to run (corrupt download?)."

mv -f "$TMP" "${INSTALL_DIR}/${ASSET}"
trap - EXIT

info "installed $("${INSTALL_DIR}/${ASSET}" --version) at ${BOLD}${INSTALL_DIR}/${ASSET}${RESET}"

# PATH check + final hint. Silenced when invoked from `steam-manager update`
# (which already knows the user has the binary on PATH).
if [ "${STEAM_MANAGER_QUIET:-0}" != "1" ]; then
    case ":$PATH:" in
        *":${INSTALL_DIR}:"*) ;;
        *)
            warn "${INSTALL_DIR} is not on your PATH."
            warn "add this line to ~/.bashrc, ~/.zshrc, or ~/.profile:"
            printf '\n    %sexport PATH="%s:$PATH"%s\n\n' "$BOLD" "$INSTALL_DIR" "$RESET"
            ;;
    esac

    info "try it: ${BOLD}${ASSET} list${RESET}"
fi
