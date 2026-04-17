#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ensure_runtime_env
require_command python3

SQL_FILE="${SQL_FILE:-${APP_DIR}/sql/init.sql}"
INFRA_POSTGRES_CONTAINER_NAME="${INFRA_POSTGRES_CONTAINER_NAME:-app-infra-postgres}"

if [[ ! -f "$SQL_FILE" ]]; then
  echo "Missing SQL file: $SQL_FILE" >&2
  exit 1
fi

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

echo "==> Applying project SQL schema: $SQL_FILE"
docker exec -i \
  -e APP_DB_NAME="$app_db_name" \
  -e APP_DB_USER="$app_db_user" \
  -e APP_DB_PASSWORD="$app_db_password" \
  "$INFRA_POSTGRES_CONTAINER_NAME" \
  sh -lc '
    PGPASSWORD="$APP_DB_PASSWORD" \
      psql -q -h 127.0.0.1 -U "$APP_DB_USER" -d "$APP_DB_NAME" -v ON_ERROR_STOP=1
  ' < "$SQL_FILE"

echo "✅ Project SQL applied"
