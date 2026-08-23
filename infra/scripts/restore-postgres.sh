#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || "$2" != "--confirm-replace-market-intel" ]]; then
  echo "Usage: $0 s3://bucket/backups/database/file.dump --confirm-replace-market-intel" >&2
  exit 2
fi
BACKUP_URI=$1
if [[ ! "$BACKUP_URI" =~ ^s3://[a-z0-9][a-z0-9.-]+/backups/database/[A-Za-z0-9._-]+\.dump$ ]]; then
  echo "Backup URI must target the database-backup prefix" >&2
  exit 2
fi

CONFIG_FILE=${FIELDINTEL_BACKUP_CONFIG:-/etc/fieldintel/backup.conf}
if [[ ! -r "$CONFIG_FILE" || -L "$CONFIG_FILE" || $(stat -c '%u' "$CONFIG_FILE") != 0 ]]; then
  echo "Backup configuration must be a readable, root-owned, non-symlink file" >&2
  exit 1
fi
source "$CONFIG_FILE"
: "${APP_DIR:=/opt/fieldintel/current}"
: "${RUNTIME_ENV_FILE:=/etc/fieldintel/runtime.env}"
COMPOSE_FILE="$APP_DIR/docker-compose.production.yml"
test -f "$COMPOSE_FILE"
test -r "$RUNTIME_ENV_FILE"
source "$(dirname "$0")/release-env.sh" "$APP_DIR/release.json"

# Preserve the current database before performing the explicitly confirmed,
# destructive replacement.
"$(dirname "$0")/backup-postgres.sh"

RESTORE_DIR=$(mktemp -d /var/lib/docker/fieldintel-db-restore.XXXXXX)
cleanup() {
  rm -f -- "$RESTORE_DIR/database.dump"
  rmdir -- "$RESTORE_DIR" 2>/dev/null || true
}
trap cleanup EXIT
RESTORE_FILE="$RESTORE_DIR/database.dump"
BUCKET_AND_KEY=${BACKUP_URI#s3://}
RESTORE_BUCKET=${BUCKET_AND_KEY%%/*}
RESTORE_KEY=${BUCKET_AND_KEY#*/}
RESTORE_HEAD=$(aws s3api head-object --bucket "$RESTORE_BUCKET" --key "$RESTORE_KEY" --output json)
EXPECTED_SHA256=$(jq -er '.Metadata.sha256' <<<"$RESTORE_HEAD")
EXPECTED_DATABASE_SIZE=$(jq -er '.Metadata.database_size' <<<"$RESTORE_HEAD")
ARCHIVE_SIZE=$(jq -er '.ContentLength' <<<"$RESTORE_HEAD")
AVAILABLE_BEFORE_DOWNLOAD=$(df --output=avail -B1 /var/lib/docker | tail -1 | tr -d ' ')
if [[ ! "$EXPECTED_DATABASE_SIZE" =~ ^[0-9]+$ || ! "$ARCHIVE_SIZE" =~ ^[0-9]+$ ||
      ! "$AVAILABLE_BEFORE_DOWNLOAD" =~ ^[0-9]+$ ||
      "$AVAILABLE_BEFORE_DOWNLOAD" -lt $((ARCHIVE_SIZE + 2147483648)) ]]; then
  echo "Insufficient or unverifiable free space for backup download" >&2
  exit 1
fi
aws s3 cp "$BACKUP_URI" "$RESTORE_FILE" --only-show-errors
test -s "$RESTORE_FILE"
ACTUAL_SHA256=$(sha256sum "$RESTORE_FILE" | awk '{print $1}')
if [[ ! "$EXPECTED_SHA256" =~ ^[a-f0-9]{64}$ || "$EXPECTED_SHA256" != "$ACTUAL_SHA256" ]]; then
  echo "Backup checksum verification failed; live database was not changed" >&2
  exit 1
fi
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres pg_restore --list <"$RESTORE_FILE" >/dev/null

CURRENT_DATABASE_SIZE=$(docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres \
  psql -U market_intel -d market_intel -Atc "SELECT pg_database_size('market_intel')")
AVAILABLE_NOW=$(df --output=avail -B1 /var/lib/docker | tail -1 | tr -d ' ')
if [[ ! "$CURRENT_DATABASE_SIZE" =~ ^[0-9]+$ || ! "$AVAILABLE_NOW" =~ ^[0-9]+$ ||
      $((AVAILABLE_NOW + CURRENT_DATABASE_SIZE)) -lt $((EXPECTED_DATABASE_SIZE * 3 / 2 + 2147483648)) ]]; then
  echo "Insufficient free space to expand the retained database; live database was not changed" >&2
  exit 1
fi

docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" stop api worker web
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres dropdb -U market_intel --if-exists market_intel
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres createdb -U market_intel market_intel
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" exec -T postgres \
  pg_restore -U market_intel -d market_intel --clean --if-exists --exit-on-error <"$RESTORE_FILE"

# A retained dump may predate the current application schema. Upgrade it with
# the current immutable API image before any API or worker process can write.
if ! docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
    -f "$COMPOSE_FILE" run --rm -e RUN_MIGRATIONS=1 api /bin/true; then
  echo "Restored database migration failed; application writers remain stopped" >&2
  exit 1
fi
docker compose --project-name fieldintel --env-file "$RUNTIME_ENV_FILE" \
  -f "$COMPOSE_FILE" up -d api worker web

echo "Database restored from $BACKUP_URI; run application smoke tests now."
