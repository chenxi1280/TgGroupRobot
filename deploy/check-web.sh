#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

load_base_env

DOCS_STATIC_BASE_DIR="${TGGROUPROBOT_DOCS_STATIC_BASE_DIR:-/data/infra/www/robot.telema.cn}"
WEB_HOST="${TGGROUPROBOT_WEB_HOST:-robot.telema.cn}"
DOCS_PUBLIC_URL="${TGGROUPROBOT_DOCS_PUBLIC_URL:-https://${WEB_HOST}/}"
ADMIN_PUBLIC_URL="${TGGROUPROBOT_ADMIN_PUBLIC_URL:-https://${WEB_HOST}/admin/}"
ADMIN_LOCAL_URL="${TGGROUPROBOT_ADMIN_LOCAL_URL:-http://127.0.0.1:${ADMIN_WEB_PORT:-8088}/admin/}"
HOST_NGINX_HEALTH_URL="${TGGROUPROBOT_HOST_NGINX_HEALTH_URL:-http://127.0.0.1/healthz}"
CURL_TIMEOUT_SECONDS="${CURL_TIMEOUT_SECONDS:-12}"
CHECK_ATTEMPTS="${TGGROUPROBOT_CHECK_ATTEMPTS:-6}"
CHECK_RETRY_DELAY_SECONDS="${TGGROUPROBOT_CHECK_RETRY_DELAY_SECONDS:-5}"
CONTAINER_NAME="${TGGROUPROBOT_CONTAINER_NAME:-tggrouprobot-bot}"
SKIP_STATIC_CHECK="${SKIP_STATIC_CHECK:-0}"
CHECK_HOST_NGINX="${TGGROUPROBOT_CHECK_HOST_NGINX:-1}"
CHECK_PUBLIC_URLS="${TGGROUPROBOT_CHECK_PUBLIC_URLS:-0}"

require_positive_integer() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "${name} must be a positive integer, got: ${value}" >&2
    exit 1
  fi
}

is_truthy() {
  case "${1:-}" in
    true|True|TRUE|1|yes|Yes|YES|on|On|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_admin_enabled() {
  case "${ADMIN_WEB_ENABLED:-true}" in
    false|False|FALSE|0|no|No|NO|off|Off|OFF)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

run_with_retries() {
  local label="$1"
  shift

  local attempt
  for ((attempt = 1; attempt <= CHECK_ATTEMPTS; attempt++)); do
    if "$@"; then
      return 0
    fi

    if (( attempt == CHECK_ATTEMPTS )); then
      echo "FAILED ${label} after ${CHECK_ATTEMPTS} attempt(s)" >&2
      return 1
    fi

    echo "Retrying ${label} in ${CHECK_RETRY_DELAY_SECONDS}s (attempt ${attempt}/${CHECK_ATTEMPTS})" >&2
    sleep "$CHECK_RETRY_DELAY_SECONDS"
  done
}

check_static_release() {
  if [[ "$SKIP_STATIC_CHECK" == "1" ]]; then
    echo "SKIP static release check"
    return 0
  fi

  local index_path="${DOCS_STATIC_BASE_DIR}/current/index.html"
  if [[ ! -f "$index_path" ]]; then
    echo "Missing docs-site static entry: $index_path" >&2
    return 1
  fi
  if [[ ! -s "$index_path" ]]; then
    echo "Empty docs-site static entry: $index_path" >&2
    return 1
  fi
  echo "OK static release: $index_path"
}

check_container_running() {
  local status health image

  status="$(docker inspect "$CONTAINER_NAME" --format '{{.State.Status}}' 2>/dev/null || true)"
  health="$(docker inspect "$CONTAINER_NAME" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"
  image="$(docker inspect "$CONTAINER_NAME" --format '{{.Config.Image}}' 2>/dev/null || true)"

  if [[ "$status" != "running" ]]; then
    echo "BAD container: ${CONTAINER_NAME} status=${status:-missing}" >&2
    docker logs --tail 120 "$CONTAINER_NAME" >&2 || true
    return 1
  fi

  if [[ -n "$health" && "$health" != "healthy" ]]; then
    echo "BAD container: ${CONTAINER_NAME} health=${health}" >&2
    docker logs --tail 120 "$CONTAINER_NAME" >&2 || true
    return 1
  fi

  echo "OK container: ${CONTAINER_NAME} status=${status} health=${health:-none} image=${image:-unknown}"
}

check_url() {
  local label="$1"
  local url="$2"
  shift 2
  local code
  local stderr_file

  stderr_file="$(mktemp)"
  if ! code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$CURL_TIMEOUT_SECONDS" "$@" "$url" 2>"$stderr_file")"; then
    echo "BAD ${label}: ${url} -> curl failed" >&2
    sed 's/^/  /' "$stderr_file" >&2
    rm -f "$stderr_file"
    return 1
  fi
  rm -f "$stderr_file"

  case "$code" in
    2*|3*)
      echo "OK ${label}: ${url} -> HTTP ${code}"
      ;;
    *)
      echo "BAD ${label}: ${url} -> HTTP ${code}" >&2
      return 1
      ;;
  esac
}

check_body() {
  local label="$1"
  local expected="$2"
  local url="$3"
  shift 3
  local body
  local stderr_file

  stderr_file="$(mktemp)"
  if ! body="$(curl -fsS --max-time "$CURL_TIMEOUT_SECONDS" "$@" "$url" 2>"$stderr_file")"; then
    echo "BAD ${label}: ${url} -> curl failed" >&2
    sed 's/^/  /' "$stderr_file" >&2
    rm -f "$stderr_file"
    return 1
  fi
  rm -f "$stderr_file"

  body="$(printf '%s' "$body" | tr -d '\r\n')"
  if [[ "$body" != "$expected" ]]; then
    echo "BAD ${label}: expected '${expected}', got '${body}'" >&2
    return 1
  fi

  echo "OK ${label}: ${url} -> ${body}"
}

check_host_nginx() {
  if ! is_truthy "$CHECK_HOST_NGINX"; then
    echo "SKIP host nginx checks"
    return 0
  fi

  run_with_retries "host nginx health" \
    check_body "host nginx health" "ok" "$HOST_NGINX_HEALTH_URL" -H "Host: ${WEB_HOST}"
  run_with_retries "docs via host nginx https" \
    check_url "docs via host nginx https" "https://${WEB_HOST}/" --resolve "${WEB_HOST}:443:127.0.0.1"

  if is_admin_enabled; then
    if ! run_with_retries "admin via host nginx https" \
      check_url "admin via host nginx https" "https://${WEB_HOST}/admin/" --resolve "${WEB_HOST}:443:127.0.0.1"; then
      cat >&2 <<EOF
Hint: local admin is reachable but host Nginx is not proxying /admin/ for ${WEB_HOST}.
Deploy the updated infra-compose host Nginx config, then rerun:
  bash ${APP_DIR}/deploy/check-web.sh
EOF
      return 1
    fi
  else
    echo "SKIP admin host nginx check: ADMIN_WEB_ENABLED=${ADMIN_WEB_ENABLED:-false}"
  fi
}

check_public_urls() {
  if ! is_truthy "$CHECK_PUBLIC_URLS"; then
    echo "SKIP public DNS checks (set TGGROUPROBOT_CHECK_PUBLIC_URLS=1 to enable)"
    return 0
  fi

  run_with_retries "docs public" \
    check_url "docs public" "$DOCS_PUBLIC_URL"
  if is_admin_enabled; then
    run_with_retries "admin public" \
      check_url "admin public" "$ADMIN_PUBLIC_URL"
  fi
}

require_command curl
require_positive_integer TGGROUPROBOT_CHECK_ATTEMPTS "$CHECK_ATTEMPTS"
require_positive_integer TGGROUPROBOT_CHECK_RETRY_DELAY_SECONDS "$CHECK_RETRY_DELAY_SECONDS"

run_with_retries "static release" check_static_release
run_with_retries "container running" check_container_running
if is_admin_enabled; then
  run_with_retries "admin local" \
    check_url "admin local" "$ADMIN_LOCAL_URL"
else
  echo "SKIP admin local check: ADMIN_WEB_ENABLED=${ADMIN_WEB_ENABLED:-false}"
fi
check_host_nginx
check_public_urls

echo "TgGroupRobot web checks passed"
