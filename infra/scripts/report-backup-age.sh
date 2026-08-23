#!/usr/bin/env bash
set -euo pipefail

STAMP_FILE=/opt/fieldintel/state/last-db-backup-epoch
NOW_EPOCH=$(date -u +%s)
if [[ -r "$STAMP_FILE" ]]; then
  BACKUP_EPOCH=$(<"$STAMP_FILE")
  if [[ ! "$BACKUP_EPOCH" =~ ^[0-9]{10}$ ]] || (( BACKUP_EPOCH > NOW_EPOCH )); then
    AGE_SECONDS=999999
  else
    AGE_SECONDS=$((NOW_EPOCH - BACKUP_EPOCH))
  fi
else
  AGE_SECONDS=999999
fi

aws cloudwatch put-metric-data \
  --namespace FieldIntel/Pilot \
  --metric-data "MetricName=DatabaseBackupAgeSeconds,Value=$AGE_SECONDS,Unit=Seconds"
