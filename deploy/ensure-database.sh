#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ensure_runtime_env
require_command python3

INFRA_POSTGRES_CONTAINER_NAME="${INFRA_POSTGRES_CONTAINER_NAME:-app-infra-postgres}"
INFRA_POSTGRES_MAINTENANCE_DB="${INFRA_POSTGRES_MAINTENANCE_DB:-postgres}"

eval "$(
  DATABASE_URL="$DATABASE_URL" python3 <<'PY'
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
)"

status="$(docker inspect "$INFRA_POSTGRES_CONTAINER_NAME" --format '{{.State.Status}}' 2>/dev/null || true)"
if [[ "$status" != "running" ]]; then
  echo "Infra PostgreSQL container is not running: ${INFRA_POSTGRES_CONTAINER_NAME}" >&2
  exit 1
fi

echo "==> Ensuring application database exists: ${app_db_name}"
docker exec \
  -e APP_DB_NAME="$app_db_name" \
  -e APP_DB_USER="$app_db_user" \
  -e APP_DB_PASSWORD="$app_db_password" \
  -e INFRA_POSTGRES_MAINTENANCE_DB="$INFRA_POSTGRES_MAINTENANCE_DB" \
  "$INFRA_POSTGRES_CONTAINER_NAME" \
  sh -lc '
    exists="$(
      PGPASSWORD="$APP_DB_PASSWORD" \
        psql -h 127.0.0.1 -U "$APP_DB_USER" -d "$INFRA_POSTGRES_MAINTENANCE_DB" \
        -tAc "SELECT 1 FROM pg_database WHERE datname = '\''$APP_DB_NAME'\''"
    )"
    if [[ "$exists" != "1" ]]; then
      PGPASSWORD="$APP_DB_PASSWORD" createdb -h 127.0.0.1 -U "$APP_DB_USER" "$APP_DB_NAME"
    fi
  '

echo "✅ Database ready: ${app_db_name}"
