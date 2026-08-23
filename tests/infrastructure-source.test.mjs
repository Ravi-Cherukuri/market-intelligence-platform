import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), "utf8");
}

test("pilot infrastructure keeps the approved low-cost security boundaries", async () => {
  const template = await source("infra/cloudformation/pilot.yaml");

  assert.match(template, /Default: t4g\.small/);
  assert.match(template, /CpuCredits: standard/);
  assert.match(template, /HttpTokens: required/);
  assert.match(template, /HttpPutResponseHopLimit: 2/);
  assert.match(template, /Encrypted: true/);
  assert.match(template, /AmazonSSMManagedInstanceCore/);
  assert.match(template, /WorkerMediaRole:/);
  assert.match(template, /PilotInstance:\n\s+Type: AWS::EC2::Instance\n\s+DependsOn:\n\s+- WorkerMediaRole\n\s+- DefaultInternetRoute/);
  assert.match(template, /InboundMediaWriteOnly/);
  assert.match(template, /RequiresMountsFor=\/var\/lib\/docker/);
  assert.match(template, /refresh-worker-credentials\.sh/);
  assert.match(template, /CreationPolicy:[\s\S]*?ResourceSignal:/);
  assert.match(template, /DataVolumeMountAssociation:/);
  assert.match(template, /WaitForSuccessTimeoutSeconds: 900/);
  assert.match(template, /dnf install -y docker amazon-cloudwatch-agent aws-cfn-bootstrap jq iptables-nft xfsprogs/);
  assert.doesNotMatch(template, /dnf install[^\n]*\bcurl\b/);
  assert.match(template, /--retry 5 --retry-all-errors --retry-max-time 300/);
  assert.match(template, /--connect-timeout 10 --max-time 120/);
  assert.match(template, /ebsnvme-id -b "\$candidate"/);
  assert.doesNotMatch(template, /ebsnvme-id -u "\$candidate"/);
  assert.match(template, /wipefs --noheadings --output TYPE "\$DATA_DEVICE"/);
  assert.match(template, /printf '%s' "\$SIGNATURE_TYPES" \| tr -d '\[:space:\]'/);
  assert.doesNotMatch(template, /\$\{SIGNATURE_TYPES/);
  assert.match(template, /Refusing to mount unexpected data volume filesystem/);
  assert.doesNotMatch(template, /if ! blkid "\$DATA_DEVICE"[\s\S]*?mkfs\.xfs/);
  assert.doesNotMatch(template, /FromPort: 22|ToPort: 22/);
  assert.doesNotMatch(template, /WHATSAPP_ACCESS_TOKEN|OPENAI_API_KEY|ADMIN_PASSWORD/);
});

test("stateful infrastructure is retained and private", async () => {
  const template = await source("infra/cloudformation/pilot.yaml");

  assert.match(template, /StorageBucket:\n[\s\S]*?DeletionPolicy: RetainExceptOnCreate/);
  assert.equal((template.match(/DeletionPolicy: RetainExceptOnCreate/g) ?? []).length, 6);
  assert.equal((template.match(/UpdateReplacePolicy: Retain/g) ?? []).length, 6);
  assert.match(template, /BlockPublicAcls: true/);
  assert.match(template, /BlockPublicPolicy: true/);
  assert.match(template, /IgnorePublicAcls: true/);
  assert.match(template, /RestrictPublicBuckets: true/);
  assert.match(template, /aws:SecureTransport: 'false'/);
  assert.match(template, /ApplicationRepository:\n[\s\S]*?ImageTagMutability: IMMUTABLE/);
  assert.match(template, /Service: sns\.amazonaws\.com/);
  assert.match(template, /DatabaseBackupStaleAlarm:/);
  assert.match(template, /Prefix: backups\/database\//);
  assert.doesNotMatch(template, /s3:DeleteObject/);
  assert.doesNotMatch(template, /Resource: !Sub '\$\{StorageBucket\.Arn\}\/\*'/);
});

test("production releases use ARM64 ECR digests with health-checked rollback", async () => {
  const compose = await source("docker-compose.production.yml");
  const build = await source("infra/scripts/build-release.sh");
  const activate = await source("infra/scripts/activate-release.sh");
  const releaseEnv = await source("infra/scripts/release-env.sh");
  const webDockerfile = await source("Dockerfile.web");

  assert.match(compose, /API_IMAGE:\?Set API_IMAGE to an immutable ECR digest/);
  assert.match(compose, /WEB_IMAGE:\?Set WEB_IMAGE to an immutable ECR digest/);
  assert.match(build, /--platform linux\/arm64/);
  assert.match(build, /describe-image-scan-findings/);
  assert.match(build, /CRITICAL/);
  assert.match(releaseEnv, /@sha256:/);
  assert.match(activate, /ecr get-login-password/);
  assert.match(activate, /restoring previous release/);
  assert.match(activate, /RUN_MIGRATIONS=1/);
  assert.match(activate, /health_check \"\$PREVIOUS_DIR\"/);
  assert.match(webDockerfile, /API_INTERNAL_URL=http:\/\/api:8000/);
  assert.match(activate, /\/api\/v1\/admin\/setup/);
});

test("logical backups are validated, size-checked, retained, and monitored", async () => {
  const backup = await source("infra/scripts/backup-postgres.sh");
  const health = await source("infra/scripts/report-backup-age.sh");

  assert.match(backup, /pg_dump/);
  assert.match(backup, /pg_restore --list/);
  assert.match(backup, /pg_restore[\s\S]*--exit-on-error/);
  assert.match(backup, /head-object/);
  assert.match(backup, /REMOTE_SHA256/);
  assert.match(backup, /DatabaseBackupSuccess/);
  assert.match(health, /DatabaseBackupAgeSeconds/);
});

test("budget stack retains all approved alert thresholds", async () => {
  const template = await source("infra/cloudformation/budget.yaml");

  assert.match(template, /Default: 25/);
  assert.equal((template.match(/NotificationType: ACTUAL/g) ?? []).length, 3);
  assert.equal((template.match(/NotificationType: FORECASTED/g) ?? []).length, 1);
  for (const threshold of [50, 80, 100]) {
    assert.match(template, new RegExp(`Threshold: ${threshold}`));
  }
});

test("two-gib pilot runtime omits Redis and ClamAV", async () => {
  const compose = await source("docker-compose.yml");
  const ingestion = await source("backend/app/services/ingestion.py");

  assert.doesNotMatch(compose, /^\s{2}(redis|clamav):/m);
  assert.doesNotMatch(compose, /redis_data|clamav_data/);
  assert.match(ingestion, /provider_type in \{"audio", "image"\}/);
  assert.doesNotMatch(ingestion, /provider_type in \{"audio", "image", "document"\}/);
});
