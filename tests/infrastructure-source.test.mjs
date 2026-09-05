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
  assert.match(template, /Default: fieldintel\.svabhu\.co\.in/);
  assert.doesNotMatch(template, /fieldintel\.svabhu\.com/);
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

test("managed release builds are bounded, native ARM64, and least privilege", async () => {
  const template = await source("infra/cloudformation/builder.yaml");
  const buildspec = await source("infra/codebuild/buildspec.yml");
  const starter = await source("infra/scripts/start-managed-build.sh");
  const build = await source("infra/scripts/build-release.sh");
  const packageManifest = JSON.parse(await source("package.json"));
  const dependencyPolicy = await source("pnpm-workspace.yaml");
  const lockfile = await source("pnpm-lock.yaml");
  const webDockerfile = await source("Dockerfile.web");

  assert.match(template, /ApplicationBuildProject:\n\s+Type: AWS::CodeBuild::Project/);
  assert.doesNotMatch(template, /AWS::EC2::Instance|AWS::S3::Bucket|AWS::ECR::Repository/);
  assert.match(template, /Service: codebuild\.amazonaws\.com/);
  assert.match(template, /aws:SourceAccount: !Ref AWS::AccountId/);
  assert.match(template, /aws:SourceArn:/);
  assert.match(template, /Type: ARM_CONTAINER/);
  assert.match(template, /ComputeType: BUILD_GENERAL1_SMALL/);
  assert.match(template, /Image: aws\/codebuild\/amazonlinux-aarch64-standard:3\.0/);
  assert.match(template, /PrivilegedMode: true/);
  assert.match(template, /ConcurrentBuildLimit: 1/);
  assert.match(template, /QueuedTimeoutInMinutes: 15/);
  assert.match(template, /TimeoutInMinutes: 45/);
  assert.match(template, /Visibility: PRIVATE/);
  assert.match(template, /StorageBucketName\}\/\$\{SourceObjectKey\}'/);
  assert.match(template, /StorageBucketName\}\/releases\/\*'/);
  assert.match(template, /repository\/\$\{ApplicationRepositoryName\}'/);
  assert.doesNotMatch(template, /s3:DeleteObject|ecr:\*/);
  assert.doesNotMatch(template, /ssm:|ec2:|cloudformation:|iam:/);
  assert.doesNotMatch(template, /codeconnections:|github\.com\/Ravi-Cherukuri/);
  assert.doesNotMatch(template, /Name: (WHATSAPP_ACCESS_TOKEN|OPENAI_API_KEY|ADMIN_PASSWORD)/);
  assert.match(buildspec, /docker info/);
  assert.match(buildspec, /docker buildx version/);
  assert.match(buildspec, /pnpm install --frozen-lockfile/);
  assert.match(buildspec, /test "\$\(uname -m\)" = "aarch64"/);
  assert.match(buildspec, /SOURCE_COMMIT:0:12.*CODEBUILD_BUILD_ID/);
  assert.match(buildspec, /CODEBUILD_SOURCE_VERSION/);
  assert.match(buildspec, /source-sha256/);
  assert.match(buildspec, /releases\/\$RELEASE_ID\/source\.zip/);
  assert.match(buildspec, /PYTHONPATH=backend.*pytest backend\/tests/);
  assert.match(buildspec, /pnpm test/);
  assert.match(buildspec, /pnpm lint/);
  assert.match(buildspec, /pnpm build/);
  assert.match(buildspec, /build-release\.sh "\$ECR_REPOSITORY_URI" "\$RELEASE_ID"/);
  assert.match(buildspec, /package-release\.sh "\$RELEASE_ID" "\$STORAGE_BUCKET"/);
  assert.doesNotMatch(buildspec, /deploy-release|activate-release|ssm send-command/);
  assert.ok(
    buildspec.indexOf("releases/$RELEASE_ID/source.zip") < buildspec.indexOf("package-release.sh"),
    "retained source must upload before the release checksum commit marker",
  );
  assert.match(starter, /git status --porcelain --untracked-files=normal/);
  assert.match(starter, /git archive --format=zip/);
  assert.match(starter, /--source-version "\$SOURCE_VERSION"/);
  assert.doesNotMatch(starter, /environment-variables-override/);
  assert.match(starter, /codebuild batch-get-builds/);
  assert.match(starter, /seq 1 390/);
  assert.match(starter, /FAILED\|FAULT\|STOPPED\|TIMED_OUT/);
  assert.match(build, /SOURCE_COMMIT must identify the archived Git commit/);
  assert.equal(packageManifest.packageManager, "pnpm@11.19.0");
  assert.match(lockfile, /^  sharp@0\.34\.5:/m);
  assert.match(lockfile, /^  unrs-resolver@1\.12\.2:/m);
  assert.equal(
    dependencyPolicy.trim(),
    'allowBuilds:\n  "sharp@0.34.5": false\n  "unrs-resolver@1.12.2": false',
    "dependency lifecycle scripts must remain denied at their reviewed versions",
  );
  assert.doesNotMatch(
    dependencyPolicy,
    /dangerouslyAllowAllBuilds|strictDepBuilds|onlyBuiltDependencies|ignoredBuiltDependencies|:\s*true\b|[*^~]/,
  );
  assert.match(
    webDockerfile,
    /COPY package\.json pnpm-lock\.yaml pnpm-workspace\.yaml \.\/\nRUN pnpm install --frozen-lockfile/,
  );
});

test("production releases use ARM64 ECR digests with health-checked rollback", async () => {
  const compose = await source("docker-compose.production.yml");
  const build = await source("infra/scripts/build-release.sh");
  const activate = await source("infra/scripts/activate-release.sh");
  const activationHealth = await source("infra/scripts/activation-health.sh");
  const deploy = await source("infra/scripts/deploy-release.sh");
  const packageRelease = await source("infra/scripts/package-release.sh");
  const releaseEnv = await source("infra/scripts/release-env.sh");
  const apiDockerfile = await source("backend/Dockerfile");
  const webDockerfile = await source("Dockerfile.web");

  assert.match(compose, /API_IMAGE:\?Set API_IMAGE to an immutable ECR digest/);
  assert.match(compose, /WEB_IMAGE:\?Set WEB_IMAGE to an immutable ECR digest/);
  assert.match(build, /--platform linux\/arm64/);
  assert.match(
    apiDockerfile,
    /^FROM python:3\.12\.14-alpine3\.24@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a$/m,
  );
  assert.match(apiDockerfile, /addgroup -S -g 10001 app && adduser -S -D -H -u 10001 -G app app/);
  assert.doesNotMatch(apiDockerfile, /python:3\.12-slim|addgroup --system|adduser --system/);
  assert.match(build, /API_RUNTIME_UID=\$\(docker run --rm --platform linux\/arm64/);
  assert.match(build, /--entrypoint id "\$REPOSITORY_URI:api-\$RELEASE_ID" -u/);
  assert.match(build, /\[\[ "\$API_RUNTIME_UID" == "10001" \]\]/);
  assert.match(build, /--entrypoint python "\$REPOSITORY_URI:api-\$RELEASE_ID" -c/);
  for (const moduleName of [
    "app.main",
    "app.worker",
    "boto3",
    "fastapi",
    "greenlet",
    "httptools",
    "jiter",
    "markupsafe",
    "openai",
    "openpyxl",
    "psycopg",
    "pydantic_core",
    "sqlalchemy",
    "uvicorn",
    "uvloop",
    "watchfiles",
    "websockets",
    "yaml",
  ]) {
    assert.ok(build.includes(moduleName), `API smoke must import ${moduleName}`);
  }
  assert.match(build, /assert psycopg\.pq\.__impl__ == "binary", psycopg\.pq\.__impl__/);
  assert.match(build, /describe-image-scan-findings/);
  assert.match(build, /CRITICAL/);
  assert.match(releaseEnv, /@sha256:/);
  assert.match(activate, /ecr get-login-password/);
  assert.match(activate, /restoring previous release/);
  assert.match(activate, /RUN_MIGRATIONS=1/);
  assert.match(activate, /health_check \"\$PREVIOUS_DIR\"/);
  assert.match(webDockerfile, /API_INTERNAL_URL=http:\/\/api:8000/);
  assert.match(webDockerfile, /ENV HOSTNAME=0\.0\.0\.0/);
  assert.match(activate, /source "\$RELEASE_DIR\/scripts\/activation-health\.sh"/);
  assert.match(activate, /capture_activation_diagnostics "\$RELEASE_DIR"/);
  assert.match(activationHealth, /\/api\/v1\/admin\/setup/);
  assert.match(activationHealth, /HEALTH_CHECK_TIMEOUT_SECONDS:-180/);
  assert.match(activationHealth, /failed_component=web/);
  assert.match(activationHealth, /failed_component=worker/);
  assert.match(activationHealth, /logs --tail 100 api web worker caddy/);
  assert.doesNotMatch(deploy, /aws ssm wait command-executed/);
  assert.match(deploy, /DEPLOY_POLL_MAX_ATTEMPTS:-180/);
  assert.match(deploy, /Failed\|Cancelled\|TimedOut\|Cancelling/);
  assert.match(packageRelease, /infra\/scripts\/activation-health\.sh/);
  assert.match(compose, /web:[\s\S]*?healthcheck:[\s\S]*?localhost:3000\/api\/v1\/admin\/setup/);
  assert.match(compose, /web:\n\s+condition: service_healthy/);
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
