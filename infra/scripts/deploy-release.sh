#!/usr/bin/env bash
set -euo pipefail

wait_for_ssm_command() {
  local command_id=$1 instance_id=$2 aws_region=$3
  local interval=${DEPLOY_POLL_INTERVAL_SECONDS:-5}
  local max_attempts=${DEPLOY_POLL_MAX_ATTEMPTS:-180}
  local attempt status=Pending response_code=-1 invocation
  [[ "$interval" =~ ^[0-9]+$ && "$max_attempts" =~ ^[1-9][0-9]*$ ]] || {
    echo "Deployment polling configuration must be non-negative integers" >&2
    return 2
  }
  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    # A newly-created invocation can briefly be absent from SSM's read path.
    # Treat that eventual-consistency window as Pending, but fail on known
    # terminal command states.
    if invocation=$(aws ssm get-command-invocation \
      --command-id "$command_id" --instance-id "$instance_id" \
      --region "$aws_region" --query '[Status,ResponseCode]' --output text 2>/dev/null); then
      read -r status response_code <<<"$invocation"
    else
      status=Pending
      response_code=-1
    fi
    case "$status" in
      Success)
        printf '{"Status":"%s","ResponseCode":%s}\n' "$status" "$response_code"
        return 0
        ;;
      Failed|Cancelled|TimedOut|Cancelling)
        printf '{"Status":"%s","ResponseCode":%s}\n' "$status" "$response_code" >&2
        return 1
        ;;
      Pending|InProgress|Delayed) ;;
      *) echo "Unexpected SSM command status: $status" >&2; return 1 ;;
    esac
    (( attempt == max_attempts )) && break
    sleep "$interval"
  done
  printf '{"Status":"%s","ResponseCode":%s,"TimedOutAfterSeconds":%s}\n' \
    "$status" "$response_code" "$((max_attempts * interval))" >&2
  return 1
}

if [[ ${FIELDINTEL_DEPLOY_LIBRARY_ONLY:-0} == 1 ]]; then
  return 0 2>/dev/null || exit 0
fi

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <instance-id> <release-id> <storage-bucket> <aws-region>" >&2
  exit 2
fi
INSTANCE_ID=$1
RELEASE_ID=$2
STORAGE_BUCKET=$3
AWS_REGION=$4
if [[ ! "$INSTANCE_ID" =~ ^i-[a-f0-9]{8,17}$ ]] ||
   [[ ! "$RELEASE_ID" =~ ^[A-Za-z0-9._-]{7,64}$ ]] ||
   [[ ! "$STORAGE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] ||
   [[ ! "$AWS_REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]]; then
  echo "Invalid deployment argument" >&2
  exit 2
fi

COMMANDS=$(jq -n \
  --arg release "$RELEASE_ID" \
  --arg bucket "$STORAGE_BUCKET" \
  '{commands:[
    "set -euo pipefail",
    ("install -d -m 0750 /opt/fieldintel/releases/" + $release),
    ("aws s3 cp s3://" + $bucket + "/releases/" + $release + "/release.tar.gz /tmp/release.tar.gz --only-show-errors"),
    ("aws s3 cp s3://" + $bucket + "/releases/" + $release + "/release.tar.gz.sha256 /tmp/release.tar.gz.sha256 --only-show-errors"),
    "cd /tmp && sha256sum -c release.tar.gz.sha256",
    ("tar -C /opt/fieldintel/releases/" + $release + " -xzf /tmp/release.tar.gz"),
    ("chmod 0755 /opt/fieldintel/releases/" + $release + "/scripts/*.sh"),
    ("/opt/fieldintel/releases/" + $release + "/scripts/activate-release.sh /opt/fieldintel/releases/" + $release),
    "rm -f /tmp/release.tar.gz /tmp/release.tar.gz.sha256"
  ]}')
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Activate FieldIntel release $RELEASE_ID" \
  --parameters "$COMMANDS" \
  --region "$AWS_REGION" \
  --query Command.CommandId \
  --output text)
wait_for_ssm_command "$COMMAND_ID" "$INSTANCE_ID" "$AWS_REGION"
