#!/usr/bin/env bash

set -euo pipefail

BASE_DIR="${BASE_DIR:-/data/tggrouprobot}"
SHARED_DIR="${SHARED_DIR:-${BASE_DIR}/shared}"
CURRENT_LINK="${CURRENT_LINK:-${BASE_DIR}/current}"
RELEASES_DIR="${RELEASES_DIR:-${BASE_DIR}/releases}"

usage() {
  cat <<'EOF'
Usage:
  bash deploy/rollback.sh <release-id>
EOF
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 1
fi

TARGET="$1"
if [[ -d "$TARGET" ]]; then
  RELEASE_DIR="$(cd "$TARGET" && pwd)"
else
  RELEASE_DIR="${RELEASES_DIR}/${TARGET}"
fi

if [[ ! -d "$RELEASE_DIR" ]]; then
  echo "Release not found: $TARGET" >&2
  exit 1
fi

if [[ ! -f "${RELEASE_DIR}/deploy/compose-up.sh" ]]; then
  echo "Release is missing deploy scripts: ${RELEASE_DIR}" >&2
  exit 1
fi

echo "==> Rolling back to ${RELEASE_DIR}"

APP_DIR="${RELEASE_DIR}" \
BASE_DIR="${BASE_DIR}" \
SHARED_DIR="${SHARED_DIR}" \
ENV_FILE="${SHARED_DIR}/.env" \
  bash "${RELEASE_DIR}/deploy/compose-up.sh"

ln -sfn "$RELEASE_DIR" "${CURRENT_LINK}.tmp"
mv -Tf "${CURRENT_LINK}.tmp" "$CURRENT_LINK"

echo "✅ Rollback finished"
echo "current -> $(readlink -f "$CURRENT_LINK")"
