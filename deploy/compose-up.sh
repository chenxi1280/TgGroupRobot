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

compose up -d --build --remove-orphans bot docs-site

echo "==> Container status"
compose ps

bot_status="$(docker inspect tggrouprobot-bot --format '{{.State.Status}}' 2>/dev/null || true)"
docs_status="$(docker inspect tggrouprobot-docs-site --format '{{.State.Status}}' 2>/dev/null || true)"

if [[ "$bot_status" != "running" ]]; then
  echo "Service is not running: tggrouprobot-bot (status=${bot_status:-missing})" >&2
  exit 1
fi

if [[ "$docs_status" != "running" ]]; then
  echo "Service is not running: tggrouprobot-docs-site (status=${docs_status:-missing})" >&2
  exit 1
fi

echo "✅ tggrouprobot-bot status=$bot_status"
echo "✅ tggrouprobot-docs-site status=$docs_status"
