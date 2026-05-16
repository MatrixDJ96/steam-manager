#!/usr/bin/env bash
# steam-manager release publisher.
#
# Usage:
#   ./scripts/release.sh v0.1.0 --notes-file notes.md
#   ./scripts/release.sh v0.1.0 < notes.md
#   ./scripts/release.sh v0.1.0 --notes-file notes.md --title "v0.1.0 — first stable release"
#   ./scripts/release.sh v0.1.0 --notes-file notes.md --draft
#
# Reads release notes from --notes-file (or stdin), appends a version-pinned
# ## Install section so the copy-paste command on the release page installs
# THAT release (not whatever `latest` resolves to later), then calls
# `gh release create` with the binary + sha256 attached.
#
# The supplied notes must NOT contain their own ## Install section — this
# script owns it.

set -euo pipefail

REPO="MatrixDJ96/steam-manager"
ASSET="steam-manager"

usage() {
    cat <<EOF
Usage: $0 <tag> [--title TITLE] [--notes-file PATH] [--draft]

Required:
  <tag>                 vMAJOR.MINOR.PATCH (e.g. v0.1.0) — optional -suffix accepted.

Options:
  --title TITLE         Release title (default: <tag>).
  --notes-file PATH     Read notes from PATH instead of stdin.
  --draft               Create as a draft instead of publishing.

Prerequisites:
  - dist/${ASSET} and dist/${ASSET}.sha256 (run ./scripts/build.sh).
  - gh CLI authenticated against ${REPO}.
EOF
    exit 1
}

[ $# -ge 1 ] || usage
command -v gh >/dev/null 2>&1 || { printf 'error: gh CLI required\n' >&2; exit 1; }

TAG="$1"; shift
TITLE=""
NOTES_FILE=""
DRAFT_FLAG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --title)      TITLE="$2"; shift 2 ;;
        --notes-file) NOTES_FILE="$2"; shift 2 ;;
        --draft)      DRAFT_FLAG="--draft"; shift ;;
        -h|--help)    usage ;;
        *) printf 'unknown arg: %s\n' "$1" >&2; usage ;;
    esac
done

# Tag format: vMAJOR.MINOR.PATCH with optional pre-release suffix.
if ! [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
    printf 'error: tag must look like vX.Y.Z (got: %s)\n' "$TAG" >&2
    exit 1
fi

# Required assets must exist locally.
[ -f "dist/${ASSET}" ]        || { printf 'error: dist/%s missing (run ./scripts/build.sh)\n' "$ASSET" >&2; exit 1; }
[ -f "dist/${ASSET}.sha256" ] || { printf 'error: dist/%s.sha256 missing\n' "$ASSET" >&2; exit 1; }

# Read notes from --notes-file or stdin.
if [ -n "$NOTES_FILE" ]; then
    [ -f "$NOTES_FILE" ] || { printf 'error: %s not found\n' "$NOTES_FILE" >&2; exit 1; }
    BODY="$(cat "$NOTES_FILE")"
else
    [ ! -t 0 ] || { printf 'error: no --notes-file and stdin is a tty\n' >&2; usage; }
    BODY="$(cat)"
fi

# Refuse if the user wrote their own Install section — release.sh owns it.
if printf '%s\n' "$BODY" | grep -qiE '^##[[:space:]]+Install([[:space:]]|$)'; then
    printf 'error: notes already contain a "## Install" section; release.sh owns this section\n' >&2
    exit 1
fi

# Render the pinned Install section.
INSTALL_SECTION=$(cat <<EOF

## Install

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/install.sh \\
    | STEAM_MANAGER_VERSION=${TAG} bash
\`\`\`

Linux x86_64. Pinned to **${TAG}** — the installer downloads the binary into \`~/.local/bin/\` and verifies the published \`.sha256\` before placing the file.

To uninstall: \`rm ~/.local/bin/steam-manager\`.
EOF
)

FINAL_BODY="${BODY}${INSTALL_SECTION}"

printf '==> publishing %s with pinned install section\n' "$TAG"
gh release create "$TAG" $DRAFT_FLAG \
    --title "${TITLE:-$TAG}" \
    --notes "$FINAL_BODY" \
    "dist/${ASSET}" "dist/${ASSET}.sha256"
