#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ensure_runtime_env

echo "==> Release directory: $APP_DIR"
echo "==> Compose file: $COMPOSE_FILE"
echo "==> Env file: $ENV_FILE"

echo "==> Ensuring application database exists"
bash "$SCRIPT_DIR/ensure-database.sh"

echo "==> Applying project schema"
bash "$SCRIPT_DIR/apply-schema.sh"

compose up -d --build --remove-orphans bot

echo "==> Container status"
compose ps

status="$(docker inspect tggrouprobot-bot --format '{{.State.Status}}' 2>/dev/null || true)"

if [[ "$status" != "running" ]]; then
  echo "Service is not running: tggrouprobot-bot (status=${status:-missing})" >&2
  exit 1
fi

echo "✅ tggrouprobot-bot status=$status"
