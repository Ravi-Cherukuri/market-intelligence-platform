import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("dashboard represents the agreed pilot workflows", async () => {
  const [page, uploads] = await Promise.all([
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/components/master-uploads.tsx", root), "utf8"),
  ]);
  for (const expected of [
    "Weekly intelligence",
    "Rolling seven-day view",
    "All intelligence",
    "Own business",
    "Competitors",
    "Biggest opportunities",
    "Biggest threats",
    "This week in words",
    "Supporting field evidence",
    "Download brief",
    "Admin setup",
    "WhatsApp channel",
  ]) {
    assert.match(page, new RegExp(expected, "i"));
  }
  assert.match(page, /weekly-intelligence/);
  assert.match(page, /week_ending/);
  assert.match(page, /business_scope/);
  assert.match(page, /Country/);
  assert.match(page, /State/);
  assert.match(page, /employee_code/);
  assert.match(uploads, /Upload employee master/i);
});

test("starter and deployment-specific Cloudflare metadata are removed", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("package.json", root), "utf8"),
  ]);
  assert.doesNotMatch(page, /SkeletonPreview|codex-preview/);
  assert.match(layout, /Agricultural Market Signals/);
  assert.doesNotMatch(packageJson, /vinext|wrangler|cloudflare|drizzle/);
});

test("employee master upload is wired to preview and commit APIs", async () => {
  const [component, config, template, proxy] = await Promise.all([
    readFile(new URL("app/components/master-uploads.tsx", root), "utf8"),
    readFile(new URL("next.config.ts", root), "utf8"),
    readFile(new URL("public/templates/employee-master.csv", root), "utf8"),
    readFile(new URL("proxy.ts", root), "utf8"),
  ]);
  assert.match(component, /masters\/employees\/preview/);
  assert.match(component, /submit\("commit"\)/);
  assert.match(component, /Nothing was imported/);
  assert.match(component, /Download CSV template/);
  assert.match(config, /127\.0\.0\.1:8000/);
  assert.match(template, /employee_code,employment_type/);
  assert.match(template, /whatsapp_number/);
  assert.match(proxy, /httpOnly: true/);
  assert.match(proxy, /pilot_admin_session/);
  assert.match(component, /previewControllerRef\.current\?\.abort/);
  assert.match(component, /previewedFile === file/);
});

test("production routing keeps Meta public while admin APIs use the web session", async () => {
  const [caddy, compose] = await Promise.all([
    readFile(new URL("Caddyfile", root), "utf8"),
    readFile(new URL("docker-compose.yml", root), "utf8"),
  ]);
  assert.match(caddy, /@direct_api path \/api\/v1\/webhooks\/whatsapp \/health \/ready/);
  assert.match(caddy, /handle \/api\/\*/);
  assert.match(compose, /API_INTERNAL_URL: http:\/\/api:8000/);
});
