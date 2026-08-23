#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <ecr-repository-uri> [release-id]" >&2
  exit 2
fi
REPOSITORY_URI=${1%/}
RELEASE_ID=${2:-$(git rev-parse --short=12 HEAD)}
if [[ ! "$REPOSITORY_URI" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+$ ]]; then
  echo "Invalid ECR repository URI" >&2
  exit 2
fi
if [[ ! "$RELEASE_ID" =~ ^[A-Za-z0-9._-]{7,64}$ ]]; then
  echo "Invalid release identifier" >&2
  exit 2
fi

REGISTRY=${REPOSITORY_URI%%/*}
REPOSITORY_NAME=${REPOSITORY_URI#*/}
REGION=$(awk -F. '{print $4}' <<<"$REGISTRY")
SOURCE_COMMIT=$(git rev-parse HEAD)
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing to release a dirty working tree" >&2
  exit 1
fi
python3 infra/scripts/check-migrations.py

aws ecr get-login-password --region "$REGION" |
  docker login --username AWS --password-stdin "$REGISTRY"

docker buildx build --platform linux/arm64 \
  --file backend/Dockerfile \
  --tag "$REPOSITORY_URI:api-$RELEASE_ID" \
  --push backend
docker buildx build --platform linux/arm64 \
  --file Dockerfile.web \
  --tag "$REPOSITORY_URI:web-$RELEASE_ID" \
  --push .

API_DIGEST=$(aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY_NAME" \
  --image-ids "imageTag=api-$RELEASE_ID" --query 'imageDetails[0].imageDigest' --output text)
WEB_DIGEST=$(aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY_NAME" \
  --image-ids "imageTag=web-$RELEASE_ID" --query 'imageDetails[0].imageDigest' --output text)
docker pull --platform linux/arm64 postgres:16-alpine
docker tag postgres:16-alpine "$REPOSITORY_URI:postgres-$RELEASE_ID"
docker push "$REPOSITORY_URI:postgres-$RELEASE_ID"
docker pull --platform linux/arm64 caddy:2-alpine
docker tag caddy:2-alpine "$REPOSITORY_URI:caddy-$RELEASE_ID"
docker push "$REPOSITORY_URI:caddy-$RELEASE_ID"
POSTGRES_DIGEST=$(aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY_NAME" \
  --image-ids "imageTag=postgres-$RELEASE_ID" --query 'imageDetails[0].imageDigest' --output text)
CADDY_DIGEST=$(aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY_NAME" \
  --image-ids "imageTag=caddy-$RELEASE_ID" --query 'imageDetails[0].imageDigest' --output text)
for digest in "$API_DIGEST" "$WEB_DIGEST" "$POSTGRES_DIGEST" "$CADDY_DIGEST"; do
  [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo "Invalid image digest: $digest" >&2; exit 1; }
done

wait_for_clean_scan() {
  local image_tag=$1
  local scan_json=''
  for _attempt in $(seq 1 30); do
    if scan_json=$(aws ecr describe-image-scan-findings --region "$REGION" \
      --repository-name "$REPOSITORY_NAME" --image-id "imageTag=$image_tag" 2>/dev/null); then
      if [[ $(jq -r '.imageScanStatus.status // ""' <<<"$scan_json") == "COMPLETE" ]]; then
        local critical_count
        critical_count=$(jq -r '.imageScanFindings.findingSeverityCounts.CRITICAL // 0' <<<"$scan_json")
        (( critical_count == 0 )) || { echo "$image_tag has CRITICAL ECR findings" >&2; exit 1; }
        return 0
      fi
    fi
    sleep 4
  done
  echo "ECR scan did not complete for $image_tag" >&2
  exit 1
}
wait_for_clean_scan "api-$RELEASE_ID"
wait_for_clean_scan "web-$RELEASE_ID"
wait_for_clean_scan "postgres-$RELEASE_ID"
wait_for_clean_scan "caddy-$RELEASE_ID"

mkdir -p dist/releases
jq -n \
  --arg release_id "$RELEASE_ID" \
  --arg source_commit "$SOURCE_COMMIT" \
  --arg api_image "$REPOSITORY_URI@$API_DIGEST" \
  --arg web_image "$REPOSITORY_URI@$WEB_DIGEST" \
  --arg postgres_image "$REPOSITORY_URI@$POSTGRES_DIGEST" \
  --arg caddy_image "$REPOSITORY_URI@$CADDY_DIGEST" \
  '{release_id:$release_id,source_commit:$source_commit,platform:"linux/arm64",api_image:$api_image,web_image:$web_image,postgres_image:$postgres_image,caddy_image:$caddy_image}' \
  >"dist/releases/$RELEASE_ID.json"

echo "Release manifest: dist/releases/$RELEASE_ID.json"
