#!/usr/bin/env bash

# Shared activation probes. The caller supplies RUNTIME_ENV_FILE and a release
# directory. Keeping these functions separate makes delayed-start and failure
# behavior testable without mutating a real host.

capture_activation_diagnostics() {
  local directory=$1
  local compose_file="$directory/docker-compose.production.yml"
  echo "Release activation failed; capturing bounded diagnostics" >&2
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$compose_file" ps >&2 || true
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$compose_file" logs --tail 100 api web worker caddy >&2 || true
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$compose_file" exec -T caddy caddy validate \
    --config /etc/caddy/Caddyfile --adapter caddyfile >&2 || true
}

health_check() {
  local directory=$1
  local compose_file="$directory/docker-compose.production.yml"
  local timeout_seconds=${HEALTH_CHECK_TIMEOUT_SECONDS:-180}
  local retry_sleep_seconds=${HEALTH_RETRY_SLEEP_SECONDS:-4}
  local deadline=$((SECONDS + timeout_seconds))
  local attempt=0 failed_component
  source "$directory/scripts/release-env.sh" "$directory/release.json"

  while (( SECONDS < deadline )); do
    attempt=$((attempt + 1))
    failed_component=''
    if ! docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
      -f "$compose_file" exec -T api python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready', timeout=5)"; then
      failed_component=api
    elif ! docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
      -f "$compose_file" exec -T web node -e \
      "const a=Buffer.from(process.env.ADMIN_USERNAME+':'+process.env.ADMIN_PASSWORD).toString('base64'); fetch('http://localhost:3000/api/v1/admin/setup',{headers:{authorization:'Basic '+a},signal:AbortSignal.timeout(10000)}).then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"; then
      failed_component=web
    elif ! docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
      -f "$compose_file" exec -T worker python -c "import os; os.kill(1, 0)"; then
      failed_component=worker
    elif ! docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
      -f "$compose_file" exec -T caddy caddy validate \
      --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
      failed_component=caddy
    else
      echo "Release health checks passed on attempt $attempt"
      return 0
    fi
    echo "Release health check attempt $attempt failed: $failed_component" >&2
    (( SECONDS >= deadline )) && break
    sleep "$retry_sleep_seconds"
  done

  echo "Release health-check deadline exhausted after ${timeout_seconds}s" >&2
  capture_activation_diagnostics "$directory"
  return 1
}
