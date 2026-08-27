import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const rootPath = new URL("../", import.meta.url).pathname;

async function releaseFixture() {
  const directory = await mkdtemp(join(tmpdir(), "fieldintel-health-"));
  await mkdir(join(directory, "scripts"));
  await writeFile(join(directory, "scripts", "release-env.sh"), "#!/usr/bin/env bash\ntrue\n");
  await writeFile(join(directory, "release.json"), "{}\n");
  await writeFile(join(directory, "docker-compose.production.yml"), "services: {}\n");
  return directory;
}

function runBash(script, env = {}) {
  return spawnSync("bash", ["-c", script], {
    cwd: rootPath,
    env: { ...process.env, ...env },
    encoding: "utf8",
    timeout: 10_000,
  });
}

test("activation health retries delayed web readiness and then succeeds", async () => {
  const release = await releaseFixture();
  const result = runBash(`
    set -uo pipefail
    RUNTIME_ENV_FILE=/dev/null
    web_attempts=0
    docker() {
      if [[ " $* " == *" exec -T web "* ]]; then
        web_attempts=$((web_attempts + 1))
        (( web_attempts > 2 ))
        return
      fi
      return 0
    }
    export -f docker
    source infra/scripts/activation-health.sh
    HEALTH_CHECK_TIMEOUT_SECONDS=5 HEALTH_RETRY_SLEEP_SECONDS=0 health_check "${release}"
  `);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /passed on attempt 3/);
  assert.match(result.stderr, /failed: web/);
});

test("activation health exhausts its deadline and captures bounded diagnostics", async () => {
  const release = await releaseFixture();
  const result = runBash(`
    set -uo pipefail
    RUNTIME_ENV_FILE=/dev/null
    docker() {
      if [[ " $* " == *" exec -T web "* ]]; then return 1; fi
      echo "diagnostic:$*" >&2
      return 0
    }
    export -f docker
    source infra/scripts/activation-health.sh
    HEALTH_CHECK_TIMEOUT_SECONDS=1 HEALTH_RETRY_SLEEP_SECONDS=0.1 health_check "${release}"
  `);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /deadline exhausted after 1s/);
  assert.match(result.stderr, /diagnostic:compose .* ps/);
  assert.match(result.stderr, /logs --tail 100 api web worker caddy/);
});

test("deployment polling survives more than the stock AWS waiter limit", () => {
  const result = runBash(`
    set -euo pipefail
    calls_file=$(mktemp)
    printf '0\\n' > "$calls_file"
    aws() {
      calls=$(<"$calls_file")
      calls=$((calls + 1))
      printf '%s\\n' "$calls" > "$calls_file"
      if (( calls < 22 )); then printf 'InProgress\\t-1\\n'; else printf 'Success\\t0\\n'; fi
    }
    source infra/scripts/deploy-release.sh
    DEPLOY_POLL_INTERVAL_SECONDS=0 DEPLOY_POLL_MAX_ATTEMPTS=30 wait_for_ssm_command cmd i-12345678 ap-south-1
    echo "calls=$(<"$calls_file")"
  `, { FIELDINTEL_DEPLOY_LIBRARY_ONLY: "1" });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /"Status":"Success"/);
  assert.match(result.stdout, /calls=22/);
});

test("deployment polling rejects a terminal SSM failure immediately", () => {
  const result = runBash(`
    set -uo pipefail
    calls=0
    aws() { calls=$((calls + 1)); printf 'Failed\\t1\\n'; }
    source infra/scripts/deploy-release.sh
    DEPLOY_POLL_INTERVAL_SECONDS=0 wait_for_ssm_command cmd i-12345678 ap-south-1
  `, { FIELDINTEL_DEPLOY_LIBRARY_ONLY: "1" });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /"Status":"Failed"/);
});
