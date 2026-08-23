#!/usr/bin/env bash
set -euo pipefail

# Every container is denied EC2 instance metadata. The worker receives a
# rotating, S3-only STS credential file from a host systemd job instead.
METADATA_IP=169.254.169.254
LEGACY_WORKER_IP=172.30.0.10
iptables -N DOCKER-USER 2>/dev/null || true
while iptables -C DOCKER-USER -s "$LEGACY_WORKER_IP" -d "$METADATA_IP"/32 -j ACCEPT 2>/dev/null; do
  iptables -D DOCKER-USER -s "$LEGACY_WORKER_IP" -d "$METADATA_IP"/32 -j ACCEPT
done
while iptables -C DOCKER-USER -d "$METADATA_IP"/32 -j REJECT 2>/dev/null; do
  iptables -D DOCKER-USER -d "$METADATA_IP"/32 -j REJECT
done
iptables -I DOCKER-USER 1 -d "$METADATA_IP"/32 -j REJECT
