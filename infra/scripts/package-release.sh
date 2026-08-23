#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <release-id> <storage-bucket> <aws-region>" >&2
  exit 2
fi
RELEASE_ID=$1
STORAGE_BUCKET=$2
AWS_REGION=$3
if [[ ! "$RELEASE_ID" =~ ^[A-Za-z0-9._-]{7,64}$ ]] ||
   [[ ! "$STORAGE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] ||
   [[ ! "$AWS_REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]]; then
  echo "Invalid release, bucket, or region" >&2
  exit 2
fi
MANIFEST="dist/releases/$RELEASE_ID.json"
test -s "$MANIFEST"

PACKAGE_DIR=$(mktemp -d)
cleanup() {
  if [[ -n "$PACKAGE_DIR" && -d "$PACKAGE_DIR" && ! -L "$PACKAGE_DIR" ]]; then
    case "$PACKAGE_DIR" in
      /tmp/*|/private/tmp/*|/private/var/folders/*/T/*) rm -rf -- "$PACKAGE_DIR" ;;
      *) echo "Refusing to clean unexpected temporary path: $PACKAGE_DIR" >&2 ;;
    esac
  fi
}
trap cleanup EXIT
install -d "$PACKAGE_DIR/release/scripts" "$PACKAGE_DIR/release/systemd"
install -m 0644 "$MANIFEST" "$PACKAGE_DIR/release/release.json"
install -m 0644 docker-compose.production.yml Caddyfile "$PACKAGE_DIR/release/"
install -m 0755 infra/scripts/activate-release.sh infra/scripts/backup-postgres.sh \
  infra/scripts/report-backup-age.sh infra/scripts/release-env.sh \
  infra/scripts/restore-postgres.sh infra/scripts/quiesce-host.sh \
  infra/scripts/configure-container-firewall.sh "$PACKAGE_DIR/release/scripts/"
install -m 0644 infra/systemd/fieldintel-backup.service infra/systemd/fieldintel-backup.timer \
  infra/systemd/fieldintel-backup-health.service infra/systemd/fieldintel-backup-health.timer \
  infra/systemd/fieldintel-container-firewall.service \
  "$PACKAGE_DIR/release/systemd/"

tar -C "$PACKAGE_DIR/release" -czf "$PACKAGE_DIR/release.tar.gz" .
(cd "$PACKAGE_DIR" && sha256sum release.tar.gz >release.tar.gz.sha256)
aws s3 cp "$PACKAGE_DIR/release.tar.gz" "s3://$STORAGE_BUCKET/releases/$RELEASE_ID/release.tar.gz" \
  --region "$AWS_REGION" --only-show-errors
aws s3 cp "$PACKAGE_DIR/release.tar.gz.sha256" "s3://$STORAGE_BUCKET/releases/$RELEASE_ID/release.tar.gz.sha256" \
  --region "$AWS_REGION" --only-show-errors
echo "Release package uploaded under s3://$STORAGE_BUCKET/releases/$RELEASE_ID/"
