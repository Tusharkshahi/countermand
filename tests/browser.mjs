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
  "-m", "countermand.server", "--port", "8788", "--state-dir", join(directory, "state"),
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
  assert.deepEqual(errors, [], `Browser errors: ${JSON.stringify(errors)}`);
  console.log("PASS: desktop, recovery, conflict, mobile (390/360), dialogs, and persistence.");
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
