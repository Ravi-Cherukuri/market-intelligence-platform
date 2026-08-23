#!/usr/bin/env bash
set -euo pipefail

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
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$AWS_REGION"
aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
  --region "$AWS_REGION" --query '{Status:Status,ResponseCode:ResponseCode}' --output json
