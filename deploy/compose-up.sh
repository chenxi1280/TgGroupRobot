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

export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"

echo "==> Building service images (COMPOSE_PARALLEL_LIMIT=${COMPOSE_PARALLEL_LIMIT})"
compose build bot

echo "==> Applying project schema"
bash "$SCRIPT_DIR/apply-schema.sh"

wait_for_container_ready() {
  local container_name="$1"
  local timeout_seconds="${2:-180}"
  local started_at
  started_at="$(date +%s)"

  while true; do
    local now elapsed status health
    now="$(date +%s)"
    elapsed=$((now - started_at))
    status="$(docker inspect "$container_name" --format '{{.State.Status}}' 2>/dev/null || true)"
    health="$(docker inspect "$container_name" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"

    if [[ "$status" == "running" && ( -z "$health" || "$health" == "healthy" ) ]]; then
      echo "✅ ${container_name} is ready: status=$status health=${health:-none}"
      return 0
    fi

    if [[ "$status" == "exited" || "$health" == "unhealthy" ]]; then
      echo "Service failed: ${container_name} status=${status:-unknown} health=${health:-none}" >&2
      echo "==> Recent ${container_name} logs" >&2
      docker logs --tail 200 "$container_name" >&2 || true
      return 1
    fi

    if (( elapsed >= timeout_seconds )); then
      echo "Timed out waiting for ${container_name}: status=${status:-unknown} health=${health:-none}" >&2
      echo "==> Recent ${container_name} logs" >&2
      docker logs --tail 200 "$container_name" >&2 || true
      return 1
    fi

    echo "Waiting for ${container_name} (${elapsed}s/${timeout_seconds}s): status=${status:-unknown} health=${health:-none}"
    sleep 5
  done
}

echo "==> Starting bot service"
compose up -d --no-build --remove-orphans bot
wait_for_container_ready tggrouprobot-bot 180

echo "==> Container status"
compose ps

bot_status="$(docker inspect tggrouprobot-bot --format '{{.State.Status}}' 2>/dev/null || true)"

if [[ "$bot_status" != "running" ]]; then
  echo "Service is not running: tggrouprobot-bot (status=${bot_status:-missing})" >&2
  exit 1
fi

echo "✅ tggrouprobot-bot status=$bot_status"
