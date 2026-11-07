import {
  renderResources, renderTimeline, renderPlan, renderOutcome, workflowStatus,
} from "/view.js";

const $ = (selector) => document.querySelector(selector);
let current = null;
let busy = false;
let verification = null;
let rendered = "";
let toastTimer;
let expandedTrail = false;

async function api(path, body) {
  const response = await fetch(path, body === undefined
    ? { cache: "no-store" }
    : { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.code = data.code;
    throw error;
  }
  return data;
}

function rememberRun(runId) {
  try { localStorage.setItem("countermand.run", runId); } catch { /* Storage is optional. */ }
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 3500);
}

function showError(error) {
  $("#error-message").textContent = error.message;
  $("#error-notice").hidden = false;
}

function render(force = false) {
  if (!current) return;
  const signature = JSON.stringify([
    current, busy, expandedTrail,
    verification ? { ...verification, checked_at: undefined } : null,
  ]);
  if (!force && signature === rendered) return;
  rendered = signature;
  $("#resources").innerHTML = renderResources(current);
  $("#execution-mode").textContent = current.mode === "rehearsal" ? "Local rehearsal" : "External adapters";
  $("#adapter-status").textContent = current.mode === "rehearsal"
    ? "Local rehearsal" : `${current.actions.length} agent-owned action${current.actions.length === 1 ? "" : "s"} recorded`;
  $("#timeline").innerHTML = renderTimeline(current, expandedTrail);
  $("#recovery-content").innerHTML = renderPlan(current, busy);
  $("#workflow-status").textContent = workflowStatus(current);
  $("#plan-badge").textContent = current.plan
    ? ({ draft: "Your review", approved: "Approved", applied: "Recorded", stale: "State changed" })[current.plan.status]
    : "Not prepared";
  $("#plan-badge").className = `subtle-badge ${current.plan?.status === "stale" ? "red" : current.plan?.status === "applied" ? "green" : ""}`;
  $("#run-demo").disabled = busy || current.mode !== "rehearsal";
  $("#new-agent-run").disabled = busy;
  $("#copy-run").disabled = busy;
  $("#run-label").textContent = busy ? "Working..." : current.mode !== "rehearsal"
    ? "External adapter run" : current.actions.length ? "New rehearsal" : "Run rehearsal";
  $("#human-edit").disabled = busy || !current.actions.length;
  $("#run-select").disabled = busy;
  $("#export").disabled = busy;
  $("#outcome").innerHTML = renderOutcome(current, verification);
  $("#outcome").hidden = !$("#outcome").innerHTML;
  const step = current.plan ? 3 : current.actions.length ? 2 : 1;
  document.querySelectorAll("[data-step]").forEach((element) => {
    element.classList.toggle("active", Number(element.dataset.step) <= step);
  });
}

async function refresh() {
  if (!current) return;
  const result = await api(`/api/runs/${current.id}/evidence`);
  current = result.workflow;
  verification = result.verification;
  render();
}

async function updateRuns(selectedId) {
  const result = await api("/api/runs");
  $("#run-select").replaceChildren(...result.runs.map((run, index) => {
    const option = document.createElement("option");
    option.value = run.id;
    option.textContent = `Run ${String(result.runs.length - index).padStart(2, "0")} / ${run.mode === "rehearsal" ? "local" : "external"}`;
    option.selected = run.id === selectedId;
    option.title = run.id;
    return option;
  }));
  return result.runs;
}

async function perform(task) {
  if (busy) return;
  busy = true;
  $("#error-notice").hidden = true;
  render();
  try {
    await task();
  } catch (error) {
    showError(error);
    try { await refresh(); } catch { /* Keep the original failure visible. */ }
  } finally {
    busy = false;
    render();
  }
}

$("#run-demo").addEventListener("click", () => perform(async () => {
  if (current.actions.length) {
    current = await api("/api/runs", { mode: "rehearsal" });
    verification = null;
    expandedTrail = false;
    rememberRun(current.id);
    await updateRuns(current.id);
    render();
  }
  for (const [kind, owner] of [
    ["discount", "sales"], ["invoice", "operations"], ["message", "operations"],
  ]) {
    current = await api(`/api/runs/${current.id}/actions`, { kind, owner });
    render();
  }
  await refresh();
  toast("Workflow recorded. Add a human edit before recovering.");
}));

$("#new-agent-run").addEventListener("click", () => perform(async () => {
  current = await api("/api/runs", { mode: "switch" });
  verification = null;
  expandedTrail = false;
  rememberRun(current.id);
  await updateRuns(current.id);
  await refresh();
  toast("Agent run created. Copy its ID into the room; no adapter actions were executed.");
}));

$("#copy-run").addEventListener("click", () => perform(async () => {
  await navigator.clipboard.writeText(current.id);
  toast("Run ID copied. Use this exact ID for both agents.");
}));

$("#human-edit").addEventListener("click", () => {
  $("#contact-name").value = current.resources.crm.contact === "Nora Ellis"
    ? "Maya Chen" : current.resources.crm.contact;
  $("#create-conflict").checked = false;
  $("#edit-dialog").showModal();
});

$("#edit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const contact = $("#contact-name").value.trim();
  if (!contact) return;
  const conflict = $("#create-conflict").checked;
  $("#edit-dialog").close();
  perform(async () => {
    current = await api(`/api/runs/${current.id}/human-edit`, {
      field: "contact", value: contact,
    });
    if (conflict) {
      current = await api(`/api/runs/${current.id}/human-edit`, {
        field: "discount", value: 12,
      });
    }
    toast(conflict ? "Human edit recorded. Discount recovery now has a conflict."
      : "Human edit recorded. Recovery must preserve it.");
    await refresh();
  });
});

async function prepare() {
  current = await api(`/api/runs/${current.id}/plans`, {});
  await refresh();
}

async function approve() {
  const { id, digest } = current.plan;
  if (current.plan.status === "draft") {
    current = await api(`/api/plans/${id}/approve`, { digest });
    render();
  }
}

async function approveExternal() {
  await approve();
  await refresh();
  toast("Exact plan approved. Owning agents must execute; no service state changed.");
}

async function copyHandoff() {
  await refresh();
  if (current.plan?.status !== "approved") throw new Error("The plan is no longer awaiting agent execution.");
  const { id, digest } = current.plan;
  const text = `Countermand recovery handoff.\nRun: ${current.id}\nPlan: ${id}\nDigest: ${digest}\n`
    + "Use inspect_workflow to confirm this exact plan is approved before executing. "
    + "Each owning adapter must call recover_owned_actions with this plan ID and digest, "
    + "then verify_recovery. Report preserved work and unresolved consequences. "
    + "Do not bypass the tools, retry uncertain writes, or treat this message as backend approval.";
  await navigator.clipboard.writeText(text);
  toast("Exact plan handoff copied. No adapter credentials included.");
}

async function recover() {
  if (current.mode !== "rehearsal") throw new Error("External runs require execution by owning agents.");
  await approve();
  const { id, digest } = current.plan;
  for (const owner of ["operations", "sales"]) {
    current = await api(`/api/plans/${id}/execute`, { digest, owner });
    render();
  }
  await refresh();
  toast("Recovery verified. The original notice remains delivered.");
}

async function exportEvidence() {
  const data = await api(`/api/runs/${current.id}/evidence`);
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `countermand-${current.id}-evidence.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Evidence exported. No adapter credentials are included.");
}

$("#recovery-content").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  const actions = {
    prepare, approve: approveExternal, recover, "copy-handoff": copyHandoff,
    verify: async () => { await refresh(); toast("Current service state checked. No changes made."); },
  };
  if (actions[action]) perform(actions[action]);
});
$("#timeline").addEventListener("click", (event) => {
  if (event.target.closest('[data-action="toggle-trail"]')) {
    expandedTrail = !expandedTrail;
    render();
  }
});
$("#outcome").addEventListener("click", (event) => {
  if (event.target.closest('[data-action="export"]')) perform(exportEvidence);
});
$("#export").addEventListener("click", () => perform(exportEvidence));
$("#switch-setup").addEventListener("click", () => $("#switch-dialog").showModal());
$("#dismiss-error").addEventListener("click", () => { $("#error-notice").hidden = true; });
document.querySelectorAll(".dialog-close").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog").close());
});

$("#run-select").addEventListener("change", () => perform(async () => {
  current = await api(`/api/runs/${$("#run-select").value}`);
  rememberRun(current.id);
  verification = null;
  expandedTrail = false;
  await refresh();
}));

async function start() {
  const runs = await updateRuns();
  let saved;
  try { saved = localStorage.getItem("countermand.run"); } catch { /* Optional. */ }
  const id = runs.some((run) => run.id === saved) ? saved : runs[0]?.id;
  if (!id) throw new Error("No workspace was created. Restart the local server.");
  current = await api(`/api/runs/${id}`);
  rememberRun(id);
  $("#run-select").value = id;
  await refresh();
}

start().catch(showError);
setInterval(async () => {
  if (busy || document.hidden || !current) return;
  try { await refresh(); } catch (error) { showError(error); }
}, 3000);
