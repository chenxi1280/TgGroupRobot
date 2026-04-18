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

parse_database_url_from_image() {
  local image="$1"

  if [[ -z "$image" ]]; then
    echo "Missing image variable for parsing DATABASE_URL" >&2
    return 1
  fi

  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "Missing release image: ${image}. Pull the current release image first." >&2
    return 1
  fi

  DATABASE_URL="$DATABASE_URL" docker run --rm -i --entrypoint python -e DATABASE_URL "$image" - <<'PY'
import os
import shlex
from urllib.parse import unquote, urlsplit

url = os.environ["DATABASE_URL"]
parts = urlsplit(url)
user = unquote(parts.username or "")
password = unquote(parts.password or "")
database = (parts.path or "").lstrip("/")

if not user or not password or not database:
    raise SystemExit("DATABASE_URL must include username, password, and database name")

for key, value in {
    "app_db_user": user,
    "app_db_password": password,
    "app_db_name": database,
}.items():
    print(f"{key}={shlex.quote(value)}")
PY
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

  case "${ADMIN_WEB_ENABLED:-true}" in
    false|False|FALSE|0|no|No|NO)
      return 0
      ;;
  esac

  case "${ADMIN_WEB_HOST:-0.0.0.0}" in
    127.0.0.1|localhost|::1)
      cat >&2 <<'EOF'
Invalid production admin web binding: ADMIN_WEB_HOST is loopback-only.

docker-compose.server.yml publishes the admin service through Docker port mapping.
Inside the bot container the FastAPI admin server must bind ADMIN_WEB_HOST=0.0.0.0,
while ADMIN_WEB_PUBLISH_HOST=127.0.0.1 keeps the published port private to the host.
EOF
      exit 1
      ;;
  esac
}

compose() {
  (cd "$APP_DIR" && docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@")
}
