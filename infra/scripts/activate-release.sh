#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <absolute-release-directory>" >&2
  exit 2
fi
RELEASE_DIR=$(realpath "$1")
if [[ ! "$RELEASE_DIR" =~ ^/opt/fieldintel/releases/[A-Za-z0-9._-]{7,64}$ ]]; then
  echo "Release directory is outside the managed path" >&2
  exit 2
fi
MANIFEST="$RELEASE_DIR/release.json"
COMPOSE_FILE="$RELEASE_DIR/docker-compose.production.yml"
RUNTIME_ENV_FILE=/etc/fieldintel/runtime.env
test -s "$MANIFEST"
test -s "$COMPOSE_FILE"
test -r "$RUNTIME_ENV_FILE"
if [[ -L "$RUNTIME_ENV_FILE" || $(stat -c '%u' "$RUNTIME_ENV_FILE") != 0 || $(stat -c '%a' "$RUNTIME_ENV_FILE") != 600 ]]; then
  echo "runtime.env must be a root-owned, non-symlink file with mode 0600" >&2
  exit 1
fi

STORAGE_BUCKET=$(awk -F= '$1=="S3_BUCKET" {print $2; exit}' "$RUNTIME_ENV_FILE")
if [[ ! "$STORAGE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "S3_BUCKET is missing or invalid in runtime.env" >&2
  exit 1
fi

export RUNTIME_ENV_FILE
source "$RELEASE_DIR/scripts/release-env.sh" "$MANIFEST"
"$RELEASE_DIR/scripts/configure-container-firewall.sh"

REGISTRY=${API_IMAGE%%/*}
if [[ ! "$REGISTRY" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com$ ]]; then
  echo "Release images must come from the account ECR registry" >&2
  exit 1
fi
ECR_REGION=$(awk -F. '{print $4}' <<<"$REGISTRY")
for image in "$API_IMAGE" "$WEB_IMAGE" "$POSTGRES_IMAGE" "$CADDY_IMAGE"; do
  [[ "$image" == "$REGISTRY/"* ]] || {
    echo "Every runtime image must come from the account ECR registry" >&2
    exit 1
  }
done
aws ecr get-login-password --region "$ECR_REGION" |
  docker login --username AWS --password-stdin "$REGISTRY"

PREVIOUS_DIR=''
if [[ -L /opt/fieldintel/current ]]; then
  PREVIOUS_DIR=$(realpath /opt/fieldintel/current)
fi

compose_up() {
  local directory=$1
  local manifest="$directory/release.json"
  source "$directory/scripts/release-env.sh" "$manifest"
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$directory/docker-compose.production.yml" pull
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$directory/docker-compose.production.yml" up -d --remove-orphans
}

health_check() {
  local directory=$1
  local compose_file="$directory/docker-compose.production.yml"
  source "$directory/scripts/release-env.sh" "$directory/release.json"
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$compose_file" exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready', timeout=5)" &&
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$compose_file" exec -T web node -e \
    "const a=Buffer.from(process.env.ADMIN_USERNAME+':'+process.env.ADMIN_PASSWORD).toString('base64'); fetch('http://localhost:3000/api/v1/admin/setup',{headers:{authorization:'Basic '+a},signal:AbortSignal.timeout(10000)}).then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))" &&
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$compose_file" exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
}

rollback_release() {
  echo "Release activation failed; restoring previous release" >&2
  if [[ -n "$PREVIOUS_DIR" && "$PREVIOUS_DIR" != "$RELEASE_DIR" ]]; then
    compose_up "$PREVIOUS_DIR" && health_check "$PREVIOUS_DIR" || {
      echo "CRITICAL: previous release also failed its health check" >&2
      return 1
    }
  else
    docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
      -f "$COMPOSE_FILE" down --remove-orphans || true
  fi
  return 1
}

# A release after the first gets a verified logical backup before any new
# image—including PostgreSQL—is allowed to touch the durable data volume.
if [[ -n "$PREVIOUS_DIR" && -x "$PREVIOUS_DIR/scripts/backup-postgres.sh" ]]; then
  "$PREVIOUS_DIR/scripts/backup-postgres.sh" || exit 1
fi
# Pull is non-mutating. Starting the candidate PostgreSQL image is guarded by
# the same health-checked rollback as the rest of activation.
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" -f "$COMPOSE_FILE" pull || exit 1
if ! docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$COMPOSE_FILE" up -d postgres; then
  rollback_release
  exit 1
fi

# Automated builds reject destructive Alembic upgrade operations.
if ! docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$COMPOSE_FILE" run --rm -e RUN_MIGRATIONS=1 api /bin/true; then
  rollback_release
  exit 1
fi
if ! compose_up "$RELEASE_DIR" || ! health_check "$RELEASE_DIR"; then
  rollback_release
  exit 1
fi

if ! install -d -m 0755 /etc/fieldintel; then
  rollback_release
  exit 1
fi
if ! ln -sfn /opt/fieldintel/current/systemd/fieldintel-backup.service \
     /etc/systemd/system/fieldintel-backup.service ||
   ! ln -sfn /opt/fieldintel/current/systemd/fieldintel-backup.timer \
     /etc/systemd/system/fieldintel-backup.timer ||
   ! ln -sfn /opt/fieldintel/current/systemd/fieldintel-backup-health.service \
     /etc/systemd/system/fieldintel-backup-health.service ||
   ! ln -sfn /opt/fieldintel/current/systemd/fieldintel-backup-health.timer \
     /etc/systemd/system/fieldintel-backup-health.timer ||
   ! ln -sfn /opt/fieldintel/current/systemd/fieldintel-container-firewall.service \
     /etc/systemd/system/fieldintel-container-firewall.service; then
  rollback_release
  exit 1
fi

if ! cat >/etc/fieldintel/backup.conf <<CONFIG
STORAGE_BUCKET=$STORAGE_BUCKET
APP_DIR=/opt/fieldintel/current
RUNTIME_ENV_FILE=/etc/fieldintel/runtime.env
CONFIG
then
  rollback_release
  exit 1
fi
if ! chmod 0640 /etc/fieldintel/backup.conf; then
  rollback_release
  exit 1
fi

# The release pointer is the commit point. If timer startup fails, restore the
# pointer and previous containers so the deployment cannot be half-activated.
ln -sfn "$RELEASE_DIR" /opt/fieldintel/current
if ! systemctl daemon-reload ||
   ! systemctl enable fieldintel-backup.timer fieldintel-backup-health.timer ||
   ! systemctl enable fieldintel-container-firewall.service ||
   ! systemctl restart fieldintel-container-firewall.service \
      fieldintel-backup.timer fieldintel-backup-health.timer; then
  if [[ -n "$PREVIOUS_DIR" ]]; then
    ln -sfn "$PREVIOUS_DIR" /opt/fieldintel/current
    systemctl daemon-reload || true
    systemctl restart fieldintel-backup.timer fieldintel-backup-health.timer || true
  else
    rm -f /opt/fieldintel/current
    systemctl disable --now fieldintel-backup.timer fieldintel-backup-health.timer || true
  fi
  rollback_release
  exit 1
fi

echo "Activated release $(jq -r '.release_id' "$MANIFEST")"
