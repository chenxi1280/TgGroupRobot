#!/usr/bin/env bash

set -euo pipefail

BASE_DIR="${BASE_DIR:-/data/tggrouprobot}"
CURRENT_APP_DIR="${BASE_DIR}/current"
LEGACY_APP_DIR="${BASE_DIR}"

if [[ -n "${APP_DIR:-}" ]]; then
  APP_DIR="$APP_DIR"
elif [[ -L "$CURRENT_APP_DIR" || -d "$CURRENT_APP_DIR" ]]; then
  APP_DIR="$CURRENT_APP_DIR"
else
  APP_DIR="$LEGACY_APP_DIR"
fi

SHARED_DIR="${SHARED_DIR:-${BASE_DIR}/shared}"
COMPOSE_FILE="${COMPOSE_FILE:-${APP_DIR}/docker-compose.server.yml}"
IMAGE_ENV_FILE="${IMAGE_ENV_FILE:-${APP_DIR}/.image.env}"

if [[ -n "${ENV_FILE:-}" ]]; then
  ENV_FILE="$ENV_FILE"
elif [[ -f "${SHARED_DIR}/.env" ]]; then
  ENV_FILE="${SHARED_DIR}/.env"
else
  ENV_FILE="${APP_DIR}/.env"
fi

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing command: $cmd" >&2
    exit 1
  fi
}

load_base_env() {
  require_command docker

  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing env file: $ENV_FILE" >&2
    exit 1
  fi

  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  if [[ -f "$IMAGE_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$IMAGE_ENV_FILE"
  fi
  set +a
}

ensure_runtime_env() {
  load_base_env

  local required=(
    BOT_TOKEN
    DATABASE_URL
  )

  local missing=()
  local key
  for key in "${required[@]}"; do
    if [[ -z "${!key:-}" ]]; then
      missing+=("$key")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "Missing runtime env vars: ${missing[*]}" >&2
    exit 1
  fi
}

compose() {
  (cd "$APP_DIR" && docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@")
}
