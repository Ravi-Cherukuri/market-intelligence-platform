import assert from "node:assert/strict";
import { chmod, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("archived source builds retain managed provenance without Git metadata", async (context) => {
  const directory = await mkdtemp(join(tmpdir(), "fieldintel-build-release-"));
  context.after(() => rm(directory, { recursive: true, force: true }));
  const scriptDirectory = join(directory, "infra", "scripts");
  const binaryDirectory = join(directory, "test-bin");
  await mkdir(scriptDirectory, { recursive: true });
  await mkdir(binaryDirectory, { recursive: true });
  const buildScript = await readFile(new URL("infra/scripts/build-release.sh", root), "utf8");
  await writeFile(join(scriptDirectory, "build-release.sh"), buildScript);
  await chmod(join(scriptDirectory, "build-release.sh"), 0o755);
  await writeFile(join(scriptDirectory, "check-migrations.py"), "# command is stubbed\n");

  const digest = `sha256:${"a".repeat(64)}`;
  const awsStub = `#!/bin/bash
set -euo pipefail
case "$1 $2" in
  "ecr get-login-password") printf '%s\\n' token ;;
  "ecr describe-images") printf '%s\\n' '${digest}' ;;
  "ecr describe-image-scan-findings") printf '%s\\n' '{"imageScanStatus":{"status":"COMPLETE"},"imageScanFindings":{"findingSeverityCounts":{}}}' ;;
  *) printf 'Unexpected aws call: %s\\n' "$*" >&2; exit 90 ;;
esac
`;
  await writeFile(join(binaryDirectory, "aws"), awsStub);
  await writeFile(
    join(binaryDirectory, "docker"),
    "#!/bin/bash\nset -euo pipefail\nif [[ ${1:-} == login ]]; then /bin/cat >/dev/null; fi\n",
  );
  await writeFile(join(binaryDirectory, "python3"), "#!/bin/bash\nexit 0\n");
  await chmod(join(binaryDirectory, "aws"), 0o755);
  await chmod(join(binaryDirectory, "docker"), 0o755);
  await chmod(join(binaryDirectory, "python3"), 0o755);

  const sourceCommit = "b".repeat(40);
  const sourceChecksum = "c".repeat(64);
  const buildUuid = "123e4567-e89b-12d3-a456-426614174000";
  const releaseId = `${sourceCommit.slice(0, 12)}-${buildUuid}`;
  const result = spawnSync(
    "bash",
    ["infra/scripts/build-release.sh", "123456789012.dkr.ecr.ap-south-1.amazonaws.com/fieldintel", releaseId],
    {
      cwd: directory,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${binaryDirectory}:/usr/bin:/bin`,
        BUILD_ARN: `arn:aws:codebuild:ap-south-1:123456789012:build/fieldintel-pilot-application:${buildUuid}`,
        SOURCE_ARCHIVE_SHA256: sourceChecksum,
        SOURCE_COMMIT: sourceCommit,
        SOURCE_VERSION: "source-version-123",
      },
    },
  );

  assert.equal(result.status, 0, result.stderr);
  const manifest = JSON.parse(await readFile(join(directory, "dist", "releases", `${releaseId}.json`), "utf8"));
  assert.equal(manifest.source_commit, sourceCommit);
  assert.equal(manifest.source_version, "source-version-123");
  assert.equal(manifest.source_archive_sha256, sourceChecksum);
  assert.equal(manifest.build_arn.endsWith(buildUuid), true);
  assert.equal(manifest.platform, "linux/arm64");
  for (const key of ["api_image", "web_image", "postgres_image", "caddy_image"]) {
    assert.match(manifest[key], /@sha256:[a-f0-9]{64}$/);
  }
});
