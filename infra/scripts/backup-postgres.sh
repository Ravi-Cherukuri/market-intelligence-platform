#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE=${FIELDINTEL_BACKUP_CONFIG:-/etc/fieldintel/backup.conf}
if [[ ! -r "$CONFIG_FILE" ]]; then
  echo "Backup configuration is not readable: $CONFIG_FILE" >&2
  exit 1
fi
if [[ -L "$CONFIG_FILE" || $(stat -c '%u' "$CONFIG_FILE") != 0 ]]; then
  echo "Backup configuration must be a root-owned, non-symlink file" >&2
  exit 1
fi
# The root-owned configuration contains deployment paths and bucket identity,
# not provider credentials. AWS access comes from the EC2 instance role.
source "$CONFIG_FILE"

: "${STORAGE_BUCKET:?STORAGE_BUCKET is required}"
: "${APP_DIR:=/opt/fieldintel/current}"
: "${RUNTIME_ENV_FILE:=/etc/fieldintel/runtime.env}"

if [[ ! "$STORAGE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "Invalid S3 bucket name" >&2
  exit 1
fi
COMPOSE_FILE="$APP_DIR/docker-compose.production.yml"
if [[ ! -f "$COMPOSE_FILE" || ! -r "$RUNTIME_ENV_FILE" ]]; then
  echo "Production compose file or runtime environment is missing" >&2
  exit 1
fi
source "$(dirname "$0")/release-env.sh" "$APP_DIR/release.json"

BACKUP_EPOCH=$(date -u +%s)
BACKUP_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=$(mktemp -d /var/lib/docker/fieldintel-db-backup.XXXXXX)
VERIFY_DATABASE="market_intel_verify_$BACKUP_EPOCH"
cleanup() {
  docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$COMPOSE_FILE" exec -T postgres \
    dropdb -U market_intel --if-exists "$VERIFY_DATABASE" >/dev/null 2>&1 || true
  rm -f -- "$BACKUP_DIR/database.dump"
  rmdir -- "$BACKUP_DIR" 2>/dev/null || true
}
trap cleanup EXIT

BACKUP_FILE="$BACKUP_DIR/database.dump"
OBJECT_KEY="backups/database/market-intel-$BACKUP_STAMP.dump"

docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U market_intel -d market_intel --format=custom >"$BACKUP_FILE"

test -s "$BACKUP_FILE"
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres pg_restore --list <"$BACKUP_FILE" >/dev/null

# A disposable restore needs roughly one additional database plus working
# headroom. Refuse safely instead of risking a full production volume.
DATABASE_SIZE=$(docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres \
  psql -U market_intel -d market_intel -Atc "SELECT pg_database_size('market_intel')")
AVAILABLE_BYTES=$(df --output=avail -B1 /var/lib/docker | tail -1 | tr -d ' ')
if [[ ! "$DATABASE_SIZE" =~ ^[0-9]+$ || ! "$AVAILABLE_BYTES" =~ ^[0-9]+$ ]]; then
  echo "Could not determine safe backup restore capacity" >&2
  exit 1
fi
REQUIRED_BYTES=$((DATABASE_SIZE * 3 / 2 + 2147483648))
if (( AVAILABLE_BYTES < REQUIRED_BYTES )); then
  echo "Insufficient free space for verified scratch restore; expand the data volume" >&2
  exit 1
fi

# Prove that the archive can be fully restored before calling it a successful
# backup. The disposable database is dropped by the EXIT trap on every path.
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres createdb -U market_intel "$VERIFY_DATABASE"
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres \
  pg_restore -U market_intel -d "$VERIFY_DATABASE" --exit-on-error <"$BACKUP_FILE"
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres dropdb -U market_intel "$VERIFY_DATABASE"

BACKUP_SHA256=$(sha256sum "$BACKUP_FILE" | awk '{print $1}')
BACKUP_SIZE=$(stat -c%s "$BACKUP_FILE")
aws s3 cp "$BACKUP_FILE" "s3://$STORAGE_BUCKET/$OBJECT_KEY" \
  --only-show-errors \
  --metadata "sha256=$BACKUP_SHA256,database_size=$DATABASE_SIZE"

REMOTE_HEAD=$(aws s3api head-object \
  --bucket "$STORAGE_BUCKET" \
  --key "$OBJECT_KEY" \
  --output json)
REMOTE_SIZE=$(jq -er '.ContentLength' <<<"$REMOTE_HEAD")
REMOTE_SHA256=$(jq -er '.Metadata.sha256' <<<"$REMOTE_HEAD")
REMOTE_DATABASE_SIZE=$(jq -er '.Metadata.database_size' <<<"$REMOTE_HEAD")
if [[ "$REMOTE_SIZE" != "$BACKUP_SIZE" ]]; then
  echo "Uploaded backup size verification failed" >&2
  exit 1
fi
if [[ "$REMOTE_SHA256" != "$BACKUP_SHA256" ]]; then
  echo "Uploaded backup checksum metadata verification failed" >&2
  exit 1
fi
if [[ "$REMOTE_DATABASE_SIZE" != "$DATABASE_SIZE" ]]; then
  echo "Uploaded backup database-size metadata verification failed" >&2
  exit 1
fi

install -d -m 0750 /opt/fieldintel/state
printf '%s\n' "$BACKUP_EPOCH" >/opt/fieldintel/state/last-db-backup-epoch
printf '%s\n' "s3://$STORAGE_BUCKET/$OBJECT_KEY" >/opt/fieldintel/state/last-db-backup-uri
chmod 0640 /opt/fieldintel/state/last-db-backup-epoch /opt/fieldintel/state/last-db-backup-uri

aws cloudwatch put-metric-data \
  --namespace FieldIntel/Pilot \
  --metric-data MetricName=DatabaseBackupSuccess,Value=1,Unit=Count
echo "Verified PostgreSQL backup uploaded: s3://$STORAGE_BUCKET/$OBJECT_KEY"
