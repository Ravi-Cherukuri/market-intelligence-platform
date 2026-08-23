#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "Usage: $0 <builder-stack-name> [aws-profile] [aws-region]" >&2
  exit 2
fi

BUILDER_STACK_NAME=$1
AWS_PROFILE_NAME=${2:-market-intelligence-pilot}
AWS_REGION_NAME=${3:-ap-south-1}
if [[ ! "$BUILDER_STACK_NAME" =~ ^[A-Za-z][-A-Za-z0-9]{0,127}$ ]] ||
   [[ ! "$AWS_PROFILE_NAME" =~ ^[A-Za-z0-9._-]{1,128}$ ]] ||
   [[ ! "$AWS_REGION_NAME" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]]; then
  echo "Invalid stack, profile, or region" >&2
  exit 2
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to build a dirty working tree" >&2
  exit 1
fi

SOURCE_COMMIT=$(git rev-parse HEAD)
[[ "$SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo "Invalid source commit" >&2; exit 1; }

STACK_OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "$BUILDER_STACK_NAME" \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --query 'Stacks[0].Outputs' \
  --output json)
BUILD_PROJECT=$(jq -er '.[] | select(.OutputKey == "ApplicationBuildProjectName") | .OutputValue' <<<"$STACK_OUTPUTS")
[[ "$BUILD_PROJECT" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{1,254}$ ]] || { echo "Invalid build project output" >&2; exit 1; }

STORAGE_BUCKET=$(aws codebuild batch-get-projects \
  --names "$BUILD_PROJECT" \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --query 'projects[0].environment.environmentVariables[?name==`STORAGE_BUCKET`].value | [0]' \
  --output text)
[[ "$STORAGE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || { echo "Invalid storage bucket in build project" >&2; exit 1; }

PACKAGE_DIR=$(mktemp -d)
cleanup() {
  if [[ -n "$PACKAGE_DIR" && -d "$PACKAGE_DIR" && ! -L "$PACKAGE_DIR" ]]; then
    case "$PACKAGE_DIR" in
      /tmp/*|/private/tmp/*|/var/folders/*/T/*|/private/var/folders/*/T/*) rm -rf -- "$PACKAGE_DIR" ;;
      *) echo "Refusing to clean unexpected temporary path: $PACKAGE_DIR" >&2 ;;
    esac
  fi
}
trap cleanup EXIT

SOURCE_ARCHIVE="$PACKAGE_DIR/source.zip"
git archive --format=zip --add-virtual-file=".fieldintel-source-commit:$SOURCE_COMMIT" \
  --output="$SOURCE_ARCHIVE" HEAD
SOURCE_SHA256=$(shasum -a 256 "$SOURCE_ARCHIVE" | awk '{print $1}')
[[ "$SOURCE_SHA256" =~ ^[a-f0-9]{64}$ ]] || { echo "Invalid source archive checksum" >&2; exit 1; }
UPLOAD_RESULT=$(aws s3api put-object \
  --bucket "$STORAGE_BUCKET" \
  --key build-sources/source.zip \
  --body "$SOURCE_ARCHIVE" \
  --metadata "source-commit=$SOURCE_COMMIT,source-sha256=$SOURCE_SHA256" \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --output json)
SOURCE_VERSION=$(jq -er '.VersionId' <<<"$UPLOAD_RESULT")

BUILD_RESULT=$(aws codebuild start-build \
  --project-name "$BUILD_PROJECT" \
  --source-version "$SOURCE_VERSION" \
  --profile "$AWS_PROFILE_NAME" \
  --region "$AWS_REGION_NAME" \
  --output json)
BUILD_ID=$(jq -er '.build.id' <<<"$BUILD_RESULT")

[[ "$BUILD_ID" == "$BUILD_PROJECT:"* ]] || { echo "Invalid CodeBuild response" >&2; exit 1; }
BUILD_UUID=${BUILD_ID#"$BUILD_PROJECT:"}
[[ "$BUILD_UUID" =~ ^[a-f0-9-]{36}$ ]] || { echo "Invalid CodeBuild build identifier" >&2; exit 1; }
RELEASE_ID="${SOURCE_COMMIT:0:12}-$BUILD_UUID"
echo "Started build: $BUILD_ID"
echo "Release ID: $RELEASE_ID"
echo "Source version: $SOURCE_VERSION"

for _attempt in $(seq 1 390); do
  BUILD_STATUS=$(aws codebuild batch-get-builds \
    --ids "$BUILD_ID" \
    --profile "$AWS_PROFILE_NAME" \
    --region "$AWS_REGION_NAME" \
    --query 'builds[0].buildStatus' \
    --output text)
  case "$BUILD_STATUS" in
    SUCCEEDED)
      echo "Build succeeded. Release $RELEASE_ID is ready for a separately approved deployment."
      exit 0
      ;;
    FAILED|FAULT|STOPPED|TIMED_OUT)
      echo "Build ended with status: $BUILD_STATUS" >&2
      exit 1
      ;;
    IN_PROGRESS)
      sleep 10
      ;;
    *)
      echo "Unexpected CodeBuild status: $BUILD_STATUS" >&2
      exit 1
      ;;
  esac
done
echo "Stopped waiting after 65 minutes; build may still be running: $BUILD_ID" >&2
exit 1
