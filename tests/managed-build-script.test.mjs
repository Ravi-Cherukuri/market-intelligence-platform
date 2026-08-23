import assert from "node:assert/strict";
import { chmod, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const root = new URL("../", import.meta.url);

function run(command, args, options = {}) {
  return spawnSync(command, args, { encoding: "utf8", ...options });
}

async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), "fieldintel-managed-build-"));
  const scriptDirectory = join(directory, "infra", "scripts");
  const binaryDirectory = join(directory, "test-bin");
  await mkdir(scriptDirectory, { recursive: true });
  await mkdir(binaryDirectory, { recursive: true });
  const starter = await readFile(new URL("infra/scripts/start-managed-build.sh", root), "utf8");
  await writeFile(join(scriptDirectory, "start-managed-build.sh"), starter);
  await chmod(join(scriptDirectory, "start-managed-build.sh"), 0o755);
  await writeFile(join(directory, "application.txt"), "tracked source\n");

  const callLog = join(directory, "aws-calls.log");
  const awsStub = `#!/bin/bash
set -euo pipefail
printf '%s\\n' "$*" >>"$AWS_CALL_LOG"
case "$1 $2" in
  "cloudformation describe-stacks")
    printf '%s\\n' '[{"OutputKey":"ApplicationBuildProjectName","OutputValue":"fieldintel-pilot-application"}]'
    ;;
  "codebuild batch-get-projects")
    printf '%s\\n' 'fieldintel-pilot-storage'
    ;;
  "s3api put-object")
    printf '%s\\n' '{"VersionId":"source-version-123"}'
    ;;
  "codebuild start-build")
    printf '%s\\n' '{"build":{"id":"fieldintel-pilot-application:123e4567-e89b-12d3-a456-426614174000"}}'
    ;;
  "codebuild batch-get-builds")
    printf '%s\\n' 'SUCCEEDED'
    ;;
  *)
    printf 'Unexpected aws call: %s\\n' "$*" >&2
    exit 90
    ;;
esac
`;
  await writeFile(join(binaryDirectory, "aws"), awsStub);
  await chmod(join(binaryDirectory, "aws"), 0o755);

  assert.equal(run("git", ["init", "-q"], { cwd: directory }).status, 0);
  assert.equal(run("git", ["add", "."], { cwd: directory }).status, 0);
  assert.equal(
    run(
      "git",
      ["-c", "user.name=FieldIntel Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
      { cwd: directory },
    ).status,
    0,
  );

  return { binaryDirectory, callLog, directory };
}

test("managed build pins the uploaded S3 version and waits for success", async (context) => {
  const { binaryDirectory, callLog, directory } = await fixture();
  context.after(() => rm(directory, { recursive: true, force: true }));
  const result = run("bash", ["infra/scripts/start-managed-build.sh", "fieldintel-pilot-builder", "pilot", "ap-south-1"], {
    cwd: directory,
    env: {
      ...process.env,
      AWS_CALL_LOG: callLog,
      PATH: `${binaryDirectory}:${process.env.PATH}`,
    },
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Release ID: [a-f0-9]{12}-123e4567-e89b-12d3-a456-426614174000/);
  assert.match(result.stdout, /Build succeeded/);
  const calls = await readFile(callLog, "utf8");
  assert.match(calls, /s3api put-object .*--key build-sources\/source\.zip/);
  assert.match(calls, /codebuild start-build .*--source-version source-version-123/);
  assert.match(calls, /s3api put-object .*--metadata source-commit=[a-f0-9]{40},source-sha256=[a-f0-9]{64}/);
  assert.match(calls, /codebuild batch-get-builds .*fieldintel-pilot-application:123e4567-e89b-12d3-a456-426614174000/);
});

test("managed build refuses untracked source before contacting AWS", async (context) => {
  const { binaryDirectory, callLog, directory } = await fixture();
  context.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(join(directory, "untracked.txt"), "not reviewed\n");
  const result = run("bash", ["infra/scripts/start-managed-build.sh", "fieldintel-pilot-builder"], {
    cwd: directory,
    env: {
      ...process.env,
      AWS_CALL_LOG: callLog,
      PATH: `${binaryDirectory}:${process.env.PATH}`,
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to build a dirty working tree/);
  await assert.rejects(readFile(callLog, "utf8"), { code: "ENOENT" });
});

test("managed build reports tracked changes before contacting AWS", async (context) => {
  const { binaryDirectory, callLog, directory } = await fixture();
  context.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(join(directory, "application.txt"), "changed after review\n");
  const result = run("bash", ["infra/scripts/start-managed-build.sh", "fieldintel-pilot-builder"], {
    cwd: directory,
    env: {
      ...process.env,
      AWS_CALL_LOG: callLog,
      PATH: `${binaryDirectory}:${process.env.PATH}`,
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to build a dirty working tree/);
  await assert.rejects(readFile(callLog, "utf8"), { code: "ENOENT" });
});
