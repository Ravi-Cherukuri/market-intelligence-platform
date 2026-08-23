#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} != "--confirm-stop-fieldintel" ]]; then
  echo "Usage: $0 --confirm-stop-fieldintel" >&2
  exit 2
fi

# Take and fully test a logical backup before stopping writers or unmounting
# the EBS data volume. Run through SSM before any approved host/attachment
# replacement change set.
/opt/fieldintel/current/scripts/backup-postgres.sh
if [[ -L /opt/fieldintel/current ]]; then
  source /opt/fieldintel/current/scripts/release-env.sh /opt/fieldintel/current/release.json
  docker compose --project-name fieldintel --env-file /etc/fieldintel/runtime.env \
    -f /opt/fieldintel/current/docker-compose.production.yml stop
fi
systemctl stop docker
sync
if mountpoint -q /var/lib/docker; then
  umount /var/lib/docker
fi
if mountpoint -q /var/lib/docker; then
  echo "Data volume is still mounted; do not execute the infrastructure change set" >&2
  exit 1
fi
echo "FieldIntel is quiesced and /var/lib/docker is unmounted."
