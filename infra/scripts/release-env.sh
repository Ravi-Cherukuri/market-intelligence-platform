#!/usr/bin/env bash
# Source this file with a release manifest to supply immutable image variables
# to every operational docker compose command.
set -euo pipefail

RELEASE_MANIFEST=${1:?Release manifest path is required}
if [[ ! -f "$RELEASE_MANIFEST" || -L "$RELEASE_MANIFEST" ]]; then
  echo "Release manifest must be a regular file" >&2
  return 1 2>/dev/null || exit 1
fi

export API_IMAGE WEB_IMAGE POSTGRES_IMAGE CADDY_IMAGE
API_IMAGE=$(jq -er '.api_image | select(test("@sha256:[a-f0-9]{64}$"))' "$RELEASE_MANIFEST")
WEB_IMAGE=$(jq -er '.web_image | select(test("@sha256:[a-f0-9]{64}$"))' "$RELEASE_MANIFEST")
POSTGRES_IMAGE=$(jq -er '.postgres_image | select(test("@sha256:[a-f0-9]{64}$"))' "$RELEASE_MANIFEST")
CADDY_IMAGE=$(jq -er '.caddy_image | select(test("@sha256:[a-f0-9]{64}$"))' "$RELEASE_MANIFEST")
