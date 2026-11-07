import { escapeHtml as e, icon } from "/view.js";
const $ = (id) => document.getElementById(id);
let state, settings, busy = false, setupForRun;
async function api(path, body) {
  const response = await fetch(`/api/github${path}`, body === undefined ? { cache: "no-store" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The pilot request failed.");
  return data;
}
function url(number) { return `https://github.com/${settings.repo}/issues/${Number(number)}`; }
function render() {
  $("gh-work").hidden = !state;
  $("gh-new").disabled = busy || !settings?.configured || !settings?.writes_enabled || !settings?.supports_task_manifest;
  if (!state) return;
  if (setupForRun !== state.id) {
    $("gh-setup").open = false;
    setupForRun = state.id;
  }
  $("gh-run-id").textContent = state.id;
  $("gh-intent").textContent = state.intent;
  const complete = state.actions.length === state.tasks.length && state.actions.every(a => a.status === "recorded");
  const uncertain = state.actions.some(a => a.status !== "recorded" || a.recovery === "unknown");
  $("gh-status").textContent = uncertain ? "Uncertain write / inspect manually" : state.plan?.status || "Authorized / ready";
  $("gh-create").disabled = busy || complete || uncertain || !settings.writes_enabled;
  $("gh-preview").disabled = busy || !complete || uncertain;
  $("gh-refresh").disabled = busy;
  $("gh-export").disabled = busy || !state.actions.length;
  $("gh-runs").disabled = busy;
  $("gh-issues").dataset.count = state.tasks.length;
  $("gh-adoption").hidden = !!state.plan;
  $("gh-issues").innerHTML = state.tasks.map((task, slot) => {
    const action = state.actions.find(a => a.slot === slot);
    const issue = action?.observed;
    const preserved = state.plan?.body.items.some(item => item.action_id === action?.id && item.classification === "preserve");
    const status = action?.status === "recorded" ? preserved ? "Preserved" : issue.state : action?.status || "Not created";
    return `<article class="resource-card"><div class="resource-top"><span class="resource-label">Task ${slot + 1}</span><span class="subtle-badge ${action?.recovery === "closed" || preserved ? "green" : ""}">${e(status)}</span></div><h3 class="gh-issue-title">${issue ? `<a href="${url(action.number)}" target="_blank" rel="noopener noreferrer">#${Number(action.number)} ${e(issue.title)}</a>` : e(task.title)}</h3><p class="resource-detail">${issue ? `${Number(issue.comments || 0)} comment${issue.comments === 1 ? "" : "s"} / ${preserved ? "newer work left open" : e(action.recovery)}` : "Authorized task. No GitHub issue exists yet."}</p></article>`;
  }).join("");
  $("gh-events").innerHTML = state.events.slice(-7).map(event => `<article class="timeline-event"><span class="event-icon">${icon("check")}</span><div><p class="event-byline">${e(event.actor)}<time>${e(new Date(event.created_at).toLocaleTimeString())}</time></p><h3 class="event-title">${e(event.title)}</h3><p class="event-description">${e(event.detail)}</p></div></article>`).join("");
  const plan = state.plan;
  $("gh-plan-status").textContent = plan?.status || "No plan";
  if (!plan) {
    $("gh-plan").innerHTML = '<div class="empty-plan"><h3>First observe. Then propose.</h3><p>Recovery will inspect current GitHub state, not assume the original receipt is still current.</p></div>';
    return;
  }
  $("gh-plan").innerHTML = plan.body.items.map(item => `<div class="plan-item"><div class="plan-item-top"><span class="plan-classification ${item.classification === "preserve" ? "repair" : ""}">${e(item.classification)}</span><a class="plan-owner" href="${url(item.number)}" target="_blank" rel="noopener noreferrer">Issue #${Number(item.number)} &nearr;</a></div><h3>${e(item.title)}</h3><p>${e(item.reason)}</p></div>`).join("")
    + `<div class="applied-note">${e(plan.body.limitation)}</div><div class="plan-signature"><span>EXACT PLAN</span><code>${e(plan.digest.slice(0, 16))}</code></div>`
    + (plan.status === "draft" ? `<label class="checkbox-label"><input type="checkbox" id="gh-ack"> I understand recovery is best-effort, not atomic.</label><button class="button button-primary plan-button" data-action="approve" ${busy ? "disabled" : ""}>Approve exact plan only</button><p class="plan-footnote">No issue closes on approval. The executor must act separately.</p>`
      : plan.status === "approved" ? `<p class="applied-note">Approved. Ask the executor in your Switch room to recover this exact plan, or use the explicitly manual pilot below.</p><button class="button button-secondary plan-button" data-action="execute" ${busy ? "disabled" : ""}>Execute approved recovery manually</button>`
        : `<p class="applied-note">${plan.status === "applied" ? "Recovery recorded. Changed issues remain for a human decision; history and announcements are not erased." : "Do not retry uncertain writes. Inspect GitHub and the receipts before proceeding."}</p>`);
}
async function perform(task) {
  if (busy) return;
  busy = true; $("gh-error").hidden = true; render();
  try { await task(); } catch (error) {
    $("gh-error").textContent = error.message; $("gh-error").hidden = false;
    if (state) try { state = await api(`/runs/${state.id}`); } catch {}
  } finally { busy = false; render(); }
}
async function list(selected) {
  const { runs } = await api("/runs");
  $("gh-runs").replaceChildren(...runs.map(run => {
    const option = document.createElement("option");
    option.value = run.id; option.textContent = `${run.intent.slice(0, 22)} / ${run.id.slice(-6)}`; option.selected = run.id === selected;
    return option;
  }));
  return runs;
}
$("gh-authorize").addEventListener("submit", event => {
  event.preventDefault();
  perform(async () => {
    const tasks = $("gh-task-input").value.split(/\r?\n/).map(title => title.trim()).filter(Boolean).map(title => ({ title }));
    state = await api("/runs", {
      confirmation: $("gh-confirm").value, intent: $("gh-intent-input").value, tasks,
    });
    await list(state.id);
  });
});
$("gh-create").addEventListener("click", () => perform(async () => {
  for (let slot = 0; slot < state.tasks.length; slot++) {
    state = await api(`/runs/${state.id}/issues`, { slot }); render();
  }
}));
$("gh-refresh").addEventListener("click", () => perform(async () => {
  state = await api(`/runs/${state.id}/inspect`);
}));
$("gh-preview").addEventListener("click", () => perform(async () => {
  state = await api(`/runs/${state.id}/plan`, {});
}));
$("gh-plan").addEventListener("click", event => {
  const action = event.target.closest("button[data-action]")?.dataset.action;
  if (!action) return;
  const acknowledged = $("gh-ack")?.checked === true;
  perform(async () => {
    if (action === "approve" && !acknowledged) throw new Error("Read and acknowledge the GitHub limitation first.");
    state = await api(`/plans/${state.plan.id}/${action}`, {
      digest: state.plan.digest, acknowledge_nonatomic: acknowledged,
    });
  });
});
$("gh-runs").addEventListener("change", () => perform(async () => {
  state = await api(`/runs/${$("gh-runs").value}`);
}));
$("gh-copy").addEventListener("click", () => perform(async () => {
  await navigator.clipboard.writeText(state.id);
}));
$("gh-export").addEventListener("click", () => perform(async () => {
  const evidence = await api(`/runs/${state.id}/evidence`);
  const href = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = href;
  link.download = `countermand-${state.id}-github.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}));
async function start() {
  settings = await api("/status");
  if (!settings.supports_task_manifest) throw new Error("Restart the Countermand backend after updating; this UI requires task-manifest support.");
  $("gh-repo").textContent = settings.repo;
  $("gh-confirm").placeholder = settings.repo;
  $("gh-config-note").textContent = settings.configured
    ? settings.writes_enabled ? "Real issue writes are enabled, but each new run still needs exact repository confirmation."
      : "GitHub configured. Restart with --github-writes only when you explicitly want real sandbox changes."
    : "On Windows: run configure-github.cmd, then start-windows.cmd --github-writes. No GitHub token is configured here.";
  const runs = await list();
  if (runs.length) state = await api(`/runs/${runs[0].id}`);
  render();
}
start().catch(error => { $("gh-error").textContent = error.message; $("gh-error").hidden = false; });
setInterval(async () => {
  if (busy || !state || document.hidden) return;
  try {
    const next = await api(`/runs/${state.id}`);
    const nextSignature = JSON.stringify(next);
    if (nextSignature !== JSON.stringify(state)) { state = next; render(); }
  } catch {}
}, 4000);
