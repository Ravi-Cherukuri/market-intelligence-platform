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
  assert.doesNotMatch(template, /FromPort: 22|ToPort: 22/);
  assert.doesNotMatch(template, /WHATSAPP_ACCESS_TOKEN|OPENAI_API_KEY|ADMIN_PASSWORD/);
});

test("stateful infrastructure is retained and private", async () => {
  const template = await source("infra/cloudformation/pilot.yaml");

  assert.match(template, /StorageBucket:\n[\s\S]*?DeletionPolicy: Retain/);
  assert.match(template, /BlockPublicAcls: true/);
  assert.match(template, /BlockPublicPolicy: true/);
  assert.match(template, /IgnorePublicAcls: true/);
  assert.match(template, /RestrictPublicBuckets: true/);
  assert.match(template, /aws:SecureTransport: 'false'/);
  assert.match(template, /ApplicationRepository:\n[\s\S]*?ImageTagMutability: IMMUTABLE/);
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
