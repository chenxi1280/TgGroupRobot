#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ensure_runtime_env

SQL_FILE="${SQL_FILE:-${APP_DIR}/sql/init.sql}"
INFRA_POSTGRES_CONTAINER_NAME="${INFRA_POSTGRES_CONTAINER_NAME:-app-infra-postgres}"

if [[ ! -f "$SQL_FILE" ]]; then
  echo "Missing SQL file: $SQL_FILE" >&2
  exit 1
fi

db_env="$(parse_database_url_from_image "${TGGROUPROBOT_BOT_IMAGE:-}")" || exit 1
eval "$db_env"

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
