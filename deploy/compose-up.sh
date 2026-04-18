#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ensure_runtime_env

echo "==> Release directory: $APP_DIR"
echo "==> Compose file: $COMPOSE_FILE"
echo "==> Env file: $ENV_FILE"

export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"

require_image() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" ]]; then
    echo "Missing image variable: ${name}. Ensure release directory contains .image.env." >&2
    exit 1
  fi
}

docker_login_ghcr() {
  if [[ "$TGGROUPROBOT_BOT_IMAGE" != ghcr.io/* && "$TGGROUPROBOT_DOCS_SITE_IMAGE" != ghcr.io/* ]]; then
    return 0
  fi

  if [[ -z "${GHCR_USERNAME:-}" || -z "${GHCR_TOKEN:-}" ]]; then
    echo "GHCR_USERNAME and GHCR_TOKEN are required to pull GHCR images." >&2
    exit 1
  fi

  printf '%s\n' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin >/dev/null
}

prune_static_releases() {
  local releases_dir="$1"
  local current_link="$2"
  local keep="${3:-5}"
  mapfile -t release_paths < <(find "$releases_dir" -mindepth 1 -maxdepth 1 -type d | sort)
  local total="${#release_paths[@]}"

  if (( total <= keep )); then
    return 0
  fi

  local current_target=""
  if [[ -L "$current_link" ]]; then
    current_target="$(readlink -f "$current_link")"
  fi

  local remove_count=$(( total - keep ))
  local idx=0
  while (( idx < remove_count )); do
    if [[ "${release_paths[$idx]}" != "$current_target" ]]; then
      rm -rf "${release_paths[$idx]}"
    fi
    idx=$((idx + 1))
  done
}

publish_static_from_image() {
  local image="$1"
  local base_dir="$2"
  local release_id="$3"
  local keep="$4"
  local html_dir="/usr/share/nginx/html"
  local releases_dir="${base_dir}/releases"
  local release_dir="${releases_dir}/${release_id}"
  local tmp_dir="${release_dir}.tmp"
  local current_link="${base_dir}/current"
  local container_id=""

  echo "==> Publishing docs-site static files: ${image} -> ${release_dir}"
  mkdir -p "$releases_dir"
  rm -rf "$tmp_dir"
  mkdir -p "$tmp_dir"

  container_id="$(docker create "$image")"
  cleanup_static_container() {
    if [[ -n "$container_id" ]]; then
      docker rm "$container_id" >/dev/null 2>&1 || true
    fi
  }
  trap 'cleanup_static_container; trap - RETURN' RETURN

  docker cp "${container_id}:${html_dir}/." "$tmp_dir/"
  test -f "${tmp_dir}/index.html"

  cleanup_static_container
  container_id=""
  trap - RETURN

  rm -rf "$release_dir"
  mv "$tmp_dir" "$release_dir"
  ln -sfn "$release_dir" "${current_link}.tmp"
  mv -Tf "${current_link}.tmp" "$current_link"
  prune_static_releases "$releases_dir" "$current_link" "$keep"
}

require_image TGGROUPROBOT_BOT_IMAGE
require_image TGGROUPROBOT_DOCS_SITE_IMAGE
docker_login_ghcr

echo "==> Pulling bot image"
compose pull bot

echo "==> Ensuring application database exists"
bash "$SCRIPT_DIR/ensure-database.sh"

echo "==> Applying project schema"
bash "$SCRIPT_DIR/apply-schema.sh"

echo "==> Pulling docs-site static artifact image"
docker pull "$TGGROUPROBOT_DOCS_SITE_IMAGE"

publish_static_from_image \
  "$TGGROUPROBOT_DOCS_SITE_IMAGE" \
  "${TGGROUPROBOT_DOCS_STATIC_BASE_DIR:-/data/infra/www/robot.telema.cn}" \
  "${STATIC_RELEASE_ID:-$(basename "$APP_DIR")}" \
  "${STATIC_KEEP_RELEASES:-5}"

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
