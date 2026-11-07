// Dependency-free Chrome DevTools smoke test. No user's browser profile is used.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const chromePath = process.env.CHROME_PATH
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
assert(existsSync(chromePath), "Set CHROME_PATH to a Chrome executable.");
const artifacts = join(root, ".countermand", "browser-tests");
mkdirSync(artifacts, { recursive: true });
const directory = mkdtempSync(join(artifacts, "run-"));
const base = "http://127.0.0.1:8788";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const backend = spawn(process.env.PYTHON || "python3", [
  "-c", "import sys; sys.path.insert(0, 'tests'); from browser_fixture import main; main()",
  "--port", "8788", "--state-dir", join(directory, "state"),
], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let backendLogs = "";
backend.stdout.on("data", (data) => { backendLogs += data; });
backend.stderr.on("data", (data) => { backendLogs += data; });
let chrome;
let socket;
let target;
let sessionId;
const pending = new Map();
const errors = [];
let sequence = 0;

async function until(check, message, timeout = 12000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const result = await check();
    if (result) return result;
    await sleep(75);
  }
  throw new Error(`Timed out: ${message}`);
}

function send(method, params = {}, session = sessionId) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`CDP timed out: ${method}`));
    }, 15000);
    pending.set(id, {
      resolve: (value) => { clearTimeout(timer); resolve(value); },
      reject: (error) => { clearTimeout(timer); reject(error); },
    });
    socket.send(JSON.stringify({ id, method, params, ...(session ? { sessionId: session } : {}) }));
  });
}

async function evaluate(expression) {
  const response = await send("Runtime.evaluate", {
    expression, awaitPromise: true, returnByValue: true, userGesture: true,
  });
  if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
  return response.result.value;
}

const waitFor = (expression, message) => until(() => evaluate(expression), message);
const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);

async function screenshot(name) {
  await evaluate("Promise.all(document.getAnimations().map(a => a.finished.catch(() => {})))");
  const image = await send("Page.captureScreenshot", {
    format: "png", captureBeyondViewport: true,
  });
  writeFileSync(join(directory, `${name}.png`), Buffer.from(image.data, "base64"));
}

try {
  await until(async () => {
    if (backend.exitCode !== null) throw new Error(`Backend exited: ${backendLogs}`);
    try { return (await fetch(`${base}/health`)).ok; } catch { return false; }
  }, "local test server", 30000);
  chrome = spawn(chromePath, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--disable-component-update",
    "--remote-debugging-port=0", `--user-data-dir=${join(directory, "chrome")}`,
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
    "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });
  let chromeLogs = "";
  chrome.stderr.on("data", (data) => { chromeLogs += data; });
  const portFile = join(directory, "chrome", "DevToolsActivePort");
  await until(() => {
    if (chrome.exitCode !== null) throw new Error(`Chrome exited: ${chromeLogs}`);
    return existsSync(portFile);
  }, "Chrome debugging port", 20000);
  const [port, socketPath] = readFileSync(portFile, "utf8").trim().split("\n");
  socket = new WebSocket(`ws://127.0.0.1:${port}${socketPath}`);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const callback = pending.get(message.id);
      if (!callback) return;
      pending.delete(message.id);
      if (message.error) callback.reject(new Error(JSON.stringify(message.error)));
      else callback.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails);
    } else if (message.method === "Log.entryAdded"
               && message.params.entry.level === "error") {
      errors.push(message.params.entry);
    }
  });
  target = (await send("Target.createTarget", { url: "about:blank" }, null)).targetId;
  sessionId = (await send("Target.attachToTarget", { targetId: target, flatten: true }, null)).sessionId;
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false,
  });
  await send("Page.navigate", { url: base });
  await waitFor("document.querySelectorAll('.resource-card').length === 3", "initial render");
  assert.equal(await evaluate("document.querySelector('#human-edit').disabled"), true);
  await screenshot("desktop-initial");

  await click("#run-demo");
  await waitFor("document.querySelectorAll('.receipt-details').length === 3 && !document.querySelector('#human-edit').disabled", "workflow actions");
  assert.equal(await evaluate("document.querySelector('#error-notice').hidden"), true);
  await click("#human-edit");
  await waitFor("document.querySelector('#edit-dialog').open", "human edit dialog");
  await evaluate(`document.querySelector('#contact-name').value = 'Maya Chen';
    document.querySelector('#edit-form').requestSubmit();`);
  await waitFor("document.querySelector('#resources').textContent.includes('Maya Chen')", "saved human edit");
  await click('[data-action="prepare"]');
  await waitFor("document.querySelectorAll('.plan-item').length === 3 && !document.querySelector('[data-action=\"recover\"]').disabled", "recovery preview");
  await screenshot("desktop-plan");
  await click('[data-action="recover"]');
  await waitFor("document.querySelector('#workflow-status').textContent.includes('Recovered /') && !document.querySelector('#outcome').hidden", "recovery outcome");
  assert.equal(await evaluate("document.querySelector('#resources').textContent.includes('Maya Chen')"), true);
  assert.equal(await evaluate("document.querySelector('#resources').textContent.includes('Voided')"), true);
  assert.equal(await evaluate("document.querySelector('#resources').textContent.includes('Correction drafted. Not sent.')"), true);
  await screenshot("desktop-recovered");
  await send("Browser.setDownloadBehavior", {
    behavior: "allow", downloadPath: directory,
  }, null);
  await click("#export");
  const exported = join(directory, `countermand-${await evaluate("document.querySelector('#run-select').value")}-evidence.json`);
  await until(() => existsSync(exported), "evidence download");
  const evidence = JSON.parse(readFileSync(exported, "utf8"));
  assert.equal(evidence.verification.all_supported_repairs_verified, true);
  assert.equal(evidence.verification.preserved_human_edits[0].passed, true);
  await waitFor("!document.querySelector('#run-demo').disabled", "export completion");

  await click("#run-demo");
  await waitFor("!document.querySelector('#human-edit').disabled && document.querySelector('#workflow-status').textContent === 'Workflow completed'", "second rehearsal");
  await click("#human-edit");
  await evaluate(`document.querySelector('#create-conflict').checked = true;
    document.querySelector('#edit-form').requestSubmit();`);
  await waitFor("document.querySelector('#resources').textContent.includes('12%')", "conflicting human edit");
  await click('[data-action="prepare"]');
  await waitFor("document.querySelector('.plan-classification.blocked')", "conflict in preview");
  await click('[data-action="recover"]');
  await waitFor("document.querySelector('#workflow-status').textContent.includes('Human decision')", "partial recovery");
  assert.equal(await evaluate("document.querySelector('#resources').textContent.includes('12%')"), true);
  await screenshot("desktop-conflict");

  await send("Emulation.setDeviceMetricsOverride", {
    width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
  });
  await screenshot("mobile-conflict");
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true,
    "Mobile layout must not overflow horizontally.");
  await send("Emulation.setDeviceMetricsOverride", {
    width: 360, height: 780, deviceScaleFactor: 1, mobile: true,
  });
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true);
  await click("#switch-setup");
  assert.equal(await evaluate("document.querySelector('#switch-dialog').open"), true);
  await evaluate("document.querySelector('#switch-dialog').close()");
  await send("Page.reload");
  await waitFor("document.querySelector('#workflow-status').textContent.includes('Human decision')", "reload persistence");

  // Exercise external approval with separate authenticated API clients, not a simulated Switch room.
  const credentials = JSON.parse(readFileSync(join(directory, "state", "credentials.json"), "utf8"));
  async function ownedRequest(path, body, role) {
    const response = await fetch(base + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Authorization": `Bearer ${credentials[role]}`, "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json();
    assert(response.ok, data.error || `API failed: ${response.status}`);
    return data;
  }
  await click("#new-agent-run");
  await waitFor("document.querySelector('#execution-mode').textContent === 'External adapters' && document.querySelector('#workflow-status').textContent === 'Awaiting agents' && !document.querySelector('#new-agent-run').disabled", "new empty agent run");
  const external = await ownedRequest(`/api/runs/${await evaluate("document.querySelector('#run-select').value")}`, undefined, "human");
  assert.equal(external.mode, "switch");
  assert.equal(external.actions.length, 0, "Creating an agent run must not impersonate adapters.");
  await ownedRequest(`/api/runs/${external.id}/actions`, { kind: "discount" }, "sales");
  await waitFor("document.querySelector('#workflow-status').textContent === 'Workflow in progress'", "partial forward workflow");
  for (const [kind, role] of [["invoice", "operations"], ["message", "operations"]]) {
    await ownedRequest(`/api/runs/${external.id}/actions`, { kind }, role);
  }
  await ownedRequest(`/api/runs/${external.id}/human-edit`, { field: "contact", value: "Maya Chen" }, "human");
  const prepared = await ownedRequest(`/api/runs/${external.id}/plans`, {}, "operations");
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false,
  });
  await send("Page.reload");
  await waitFor(`Array.from(document.querySelector('#run-select').options).some(o => o.value === ${JSON.stringify(external.id)})`, "external run selection");
  await evaluate(`document.querySelector('#run-select').value = ${JSON.stringify(external.id)};
    document.querySelector('#run-select').dispatchEvent(new Event('change'));`);
  await waitFor("document.querySelector('#execution-mode').textContent === 'External adapters' && document.querySelector('[data-action=\"approve\"]') && !document.querySelector('[data-action=\"approve\"]').disabled", "external plan");
  assert.equal(await evaluate("document.querySelector('#run-demo').disabled"), true);
  assert.equal(await evaluate("document.querySelector('.workspace-footer').textContent.includes('Switch status not monitored')"), true);
  await click('[data-action="approve"]');
  await waitFor("document.querySelector('#workflow-status').textContent === 'Recovery approved' && !document.querySelector('[data-action=\"copy-handoff\"]').disabled", "approval only");
  const approved = await ownedRequest(`/api/runs/${external.id}`, undefined, "human");
  assert.equal(approved.resources.crm.discount, 30, "Approval must not restore the discount.");
  assert.equal(approved.resources.billing.status, "draft", "Approval must not void the invoice.");
  assert(approved.actions.every(a => a.recovery === "pending"));
  await evaluate(`Object.defineProperty(navigator, 'clipboard', {
    configurable: true, value: { writeText: async text => { window.copiedHandoff = text; } }
  });`);
  await click("#copy-run");
  await waitFor(`window.copiedHandoff === ${JSON.stringify(external.id)} && !document.querySelector('[data-action="copy-handoff"]').disabled`, "copied run ID");
  await click('[data-action="copy-handoff"]');
  await waitFor("typeof window.copiedHandoff === 'string' && window.copiedHandoff.includes('Countermand recovery handoff.')", "copied handoff");
  const handoff = await evaluate("window.copiedHandoff");
  assert(handoff.includes(prepared.plan.id));
  assert(handoff.includes(prepared.plan.digest));
  assert(Object.values(credentials).every(token => !handoff.includes(token)));
  await screenshot("desktop-external-approved");
  for (const role of ["operations", "sales"]) {
    await ownedRequest(`/api/plans/${prepared.plan.id}/execute`, { digest: prepared.plan.digest }, role);
  }
  await waitFor("document.querySelector('#workflow-status').textContent.includes('Recovered /')", "external owned recovery");
  assert.equal(await evaluate("document.querySelector('#resources').textContent.includes('Maya Chen')"), true);
  assert.equal(await evaluate("document.querySelector('#resources').textContent.includes('Voided')"), true);
  await screenshot("desktop-external-recovered");

  // Real HTTP/UI workflow against the explicitly fake GitHub provider.
  await send("Page.navigate", { url: base + "/github" });
  await waitFor("document.querySelector('#gh-repo').textContent === 'Tusharkshahi/TaskMind' && !document.querySelector('#gh-new').disabled", "GitHub fixture setup");
  await evaluate(`document.querySelector('#gh-intent-input').value = 'TaskMind due-date milestone';
    document.querySelector('#gh-task-input').value = 'Add due-date validation\\nCover overdue-task sorting';
    document.querySelector('#gh-confirm').value = 'Tusharkshahi/TaskMind';
    document.querySelector('#gh-authorize').requestSubmit();`);
  await waitFor("!document.querySelector('#gh-work').hidden && document.querySelectorAll('#gh-issues .resource-card').length === 2", "authorized task manifest");
  const githubRun = await evaluate("document.querySelector('#gh-run-id').textContent");
  await click("#gh-create");
  await waitFor("document.querySelectorAll('#gh-issues a').length === 2 && !document.querySelector('#gh-preview').disabled", "created fixture issues");
  const kickoff = await ownedRequest(`/api/github/runs/${githubRun}`, undefined, "human");
  assert.deepEqual(kickoff.tasks.map(task => task.title), ["Add due-date validation", "Cover overdue-task sorting"]);
  const adoptedNumber = kickoff.actions[1].number;
  await ownedRequest("/__fixture__/adopt", {
    number: adoptedNumber, title: "Human-owned: overdue-task sorting",
  }, "human");
  await click("#gh-preview");
  await waitFor("document.querySelector('#gh-plan').textContent.includes('preserve') && !document.querySelector('#gh-plan button[data-action=\"approve\"]').disabled", "preserved adopted issue");
  await click('#gh-plan button[data-action="approve"]');
  await waitFor("!document.querySelector('#gh-error').hidden && !document.querySelector('#gh-plan button[data-action=\"approve\"]').disabled", "non-atomic acknowledgment required");
  assert.equal(await evaluate("document.querySelector('#gh-plan-status').textContent"), "draft");
  await evaluate("document.querySelector('#gh-ack').checked = true");
  await click('#gh-plan button[data-action="approve"]');
  await waitFor("document.querySelector('#gh-plan-status').textContent === 'approved' && !document.querySelector('#gh-plan button[data-action=\"execute\"]').disabled", "GitHub exact plan approved");
  const githubApproved = await ownedRequest(`/api/github/runs/${githubRun}`, undefined, "human");
  assert(githubApproved.actions.every(action => action.observed.state === "open"),
    "Approval alone must not close GitHub issues.");
  await click('#gh-plan button[data-action="execute"]');
  await waitFor("document.querySelector('#gh-plan-status').textContent === 'applied' && !document.querySelector('#gh-export').disabled", "GitHub bounded recovery");
  const recoveredGitHub = await ownedRequest(`/api/github/runs/${githubRun}`, undefined, "human");
  assert.equal(recoveredGitHub.actions[0].observed.state, "closed");
  assert.equal(recoveredGitHub.actions[1].observed.state, "open");
  assert.equal(recoveredGitHub.actions[1].observed.title, "Human-owned: overdue-task sorting");
  await screenshot("desktop-github-fixture-recovered");
  await click("#gh-export");
  const githubExport = join(directory, `countermand-${githubRun}-github.json`);
  await until(() => existsSync(githubExport), "GitHub evidence download");
  const githubEvidence = JSON.parse(readFileSync(githubExport, "utf8"));
  assert.equal(githubEvidence.verification.atomic_recovery_guaranteed, false);
  assert(githubEvidence.verification.checks.every(check => check.passed));
  for (const width of [390, 360]) {
    await send("Emulation.setDeviceMetricsOverride", {
      width, height: 844, deviceScaleFactor: 1, mobile: true,
    });
    assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true,
      `GitHub workspace must not overflow at ${width}px.`);
  }
  await screenshot("mobile-github-fixture-recovered");
  await send("Page.reload");
  await waitFor("document.querySelector('#gh-plan-status').textContent === 'applied'", "GitHub reload persistence");
  assert.deepEqual(errors, [], `Browser errors: ${JSON.stringify(errors)}`);
  console.log("PASS: desktop/mobile, local/external recovery, approval-only controls, handoff copy, GitHub task manifests, preservation, evidence, and persistence.");
  console.log(`Screenshots: ${directory}`);
} catch (error) {
  if (sessionId) await screenshot("failure").catch(() => {});
  console.error(backendLogs);
  throw error;
} finally {
  socket?.close();
  chrome?.kill("SIGTERM");
  backend.kill("SIGTERM");
}
