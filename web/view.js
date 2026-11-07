export const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const paths = {
  undo: '<path d="M7 5 3 9l4 4M3 9h9a5 5 0 0 1 0 10H9"/>',
  check: '<path d="m5 10 3.5 3.5L15 7"/>',
  shield: '<path d="m10 2 6 2v5c0 4-6 8-6 8S4 13 4 9V4l6-2Z"/><path d="m7 9 2 2 4-4"/>',
  crm: '<rect x="3" y="3" width="14" height="14" rx="3"/><circle cx="10" cy="8" r="2"/><path d="M6 15c0-4 8-4 8 0"/>',
  billing: '<path d="M5 2h10v16l-2-1-3 1-3-1-2 1V2Z"/><path d="M8 6h4M8 10h4"/>',
  mail: '<rect x="2" y="4" width="16" height="12" rx="3"/><path d="m3 5 7 6 7-6"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  warning: '<path d="m10 2 8 15H2L10 2Z"/><path d="M10 7v4m0 3v.1"/>',
};

export function icon(name) {
  return `<svg viewBox="0 0 20 20" fill="none" aria-hidden="true" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.check}</svg>`;
}

const e = escapeHtml;
const badge = (text, tone = "") => `<span class="subtle-badge ${tone}">${e(text)}</span>`;
const money = (cents) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 2,
}).format(cents / 100);

export function renderResources(state) {
  const { crm, billing, mail } = state.resources;
  const discountAction = state.actions.find((a) => a.kind === "discount");
  const recovered = discountAction?.recovery === "restored";
  const humanEdited = state.events.some((event) =>
    event.type === "human_edit" && event.detail.startsWith("Set contact "));
  const conflict = state.plan?.body.items.some((item) =>
    item.kind === "discount" && item.state === "blocked");
  const discountBadge = recovered ? badge("Restored", "green")
    : conflict ? badge("Human change", "amber")
      : discountAction ? badge("Needs recovery", "amber") : badge("Original state");
  const invoiceBadge = billing.status === "void" ? badge("Voided", "green")
    : billing.status === "draft" ? badge("Draft", "amber") : badge("Not created");
  const mailBadge = mail.status === "delivered" ? badge("Cannot unsend", "amber")
    : badge("Not sent");
  return `
    <article class="resource-card">
      <div class="resource-top"><span class="resource-label">${icon("crm")} Customer / CRM</span>${discountBadge}</div>
      <div class="resource-value">${recovered ? '<span class="previous">30%</span><span class="value-arrow" aria-label="changed to">&rarr;</span>' : ""}${e(crm.discount)}%</div>
      <p class="resource-detail">Current discount <span aria-hidden="true">&middot;</span> agreed: 3%</p>
      <p class="resource-detail">${humanEdited ? '<span class="protected">' + icon("shield") : ""}${e(crm.contact)}${humanEdited ? " &middot; human edit</span>" : " &middot; contact"}</p>
    </article>
    <article class="resource-card">
      <div class="resource-top"><span class="resource-label">${icon("billing")} Draft invoice</span>${invoiceBadge}</div>
      <div class="resource-value">${billing.status === "not_created" ? "&mdash;" : e(money(billing.amount_cents))}</div>
      <p class="resource-detail">${billing.status === "void" ? "Voided, not erased. History retained."
        : billing.status === "draft" ? `${e(billing.discount)}% discount on a $1,000.00 base`
          : "No billing changes yet."}</p>
    </article>
    <article class="resource-card">
      <div class="resource-top"><span class="resource-label">${icon("mail")} Test mailbox</span>${mailBadge}</div>
      <div class="resource-value message-value">${mail.status === "delivered" ? "Notice delivered" : "Nothing delivered"}</div>
      <p class="resource-detail">${mail.correction_status === "draft" ? "Correction drafted. Not sent."
        : mail.status === "delivered" ? "Local mailbox only. No real recipient." : "No real email will be sent."}</p>
      ${mail.status === "delivered" ? `<details class="mail-preview"><summary>Read ${mail.correction_status === "draft" ? "messages" : "notice"}</summary><p><b>Original:</b> ${e(mail.body)}</p>${mail.correction_status === "draft" ? `<p><b>Unsent correction:</b> ${e(mail.correction_body)}</p>` : ""}</details>` : ""}
    </article>`;
}

const actorLabel = {
  human: "You", Maya: "Maya / human", sales: "Sales adapter",
  operations: "Operations adapter", recovery: "Recovery engine",
  "local-demo-human": "You / local approval",
};

export function renderTimeline(state, expanded = false) {
  const events = expanded ? state.events : state.events.slice(-5);
  const trail = events.map((event) => {
    const human = ["human", "Maya"].includes(event.actor);
    const recovered = ["recovery", "approval"].includes(event.type);
    const action = event.type === "action" ? state.actions.find((a) => a.label === event.title) : null;
    const moment = new Date(event.created_at);
    const timestamp = moment.toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
    const chip = action && action.kind === "discount" ? "3% &rarr; 30%"
      : action && action.kind === "invoice" ? "$700.00 / draft"
        : action && action.kind === "message" ? "Delivered / local mailbox" : null;
    return `<article class="timeline-event">
      <span class="event-icon ${human ? "human" : recovered ? "recovered" : event.type === "conflict" ? "conflict" : ""}">${human ? event.actor === "Maya" ? "MC" : "Y" : icon(event.type === "conflict" ? "warning" : recovered ? "check" : event.type === "plan" ? "undo" : "plus")}</span>
      <div>
        <p class="event-byline"><span class="actor">${e(actorLabel[event.actor] || event.actor)}</span><time datetime="${e(event.created_at)}">${e(timestamp)}</time></p>
        <h3 class="event-title">${e(event.title)}</h3>
        <p class="event-description">${e(event.detail)}</p>
        ${chip ? `<div class="event-chips"><span class="event-chip">${chip}</span><span class="event-chip">${e(action.id.slice(-8))}</span></div>` : ""}
        ${action ? `<details class="receipt-details"><summary>Inspect action receipt</summary><pre>${e(JSON.stringify({ id: action.id, owner: action.owner, changes: action.changes, recovery: action.recovery }, null, 2))}</pre></details>` : ""}
      </div>
    </article>`;
  }).join("");
  return trail + (state.events.length > 5
    ? `<button class="text-button trail-toggle" data-action="toggle-trail">${expanded ? "Show recent events" : `Show all ${state.events.length} events`} <span aria-hidden="true">${expanded ? "&uarr;" : "&darr;"}</span></button>`
    : "");
}

export function workflowStatus(state) {
  if (state.plan?.status === "stale") return "State changed / review again";
  if (state.plan?.status === "applied") {
    return state.actions.some((a) => a.recovery === "pending")
      ? "Human decision needed" : "Recovered / review remains";
  }
  if (state.plan?.status === "approved") return "Recovery approved";
  if (state.plan?.status === "draft") return "Awaiting your review";
  if (state.actions.length === 3) return "Workflow completed";
  if (state.actions.length) return "Workflow in progress";
  return state.mode === "rehearsal" ? "Ready to rehearse" : "Awaiting agents";
}

export function renderPlan(state, busy) {
  const plan = state.plan;
  if (!plan) {
    return `<div class="empty-plan">
      <span class="empty-plan-icon">${icon("undo")}</span>
      <h3>A plan before another change.</h3>
      <p>See what can be restored, what must be preserved, and what cannot be undone.</p>
    </div>
    <button class="button button-primary plan-button" data-action="prepare" ${!state.actions.length || busy ? "disabled" : ""}>Preview recovery <span aria-hidden="true">&rarr;</span></button>
    <p class="plan-footnote">No service fields change. Previewing freezes new forward actions for this run.</p>`;
  }
  const outcomes = Object.fromEntries(state.actions.map((a) => [a.id, a.recovery]));
  const items = plan.body.items.map((item) => {
    const completed = outcomes[item.action_id] !== "pending";
    const title = completed ? "Recorded" : item.state === "blocked" ? "Human decision" : item.classification;
    return `<div class="plan-item">
      <div class="plan-item-top"><span class="plan-classification ${item.state === "blocked" ? "blocked" : item.classification}">${e(title)}</span><span class="plan-owner">${e(actorLabel[item.owner])}</span>${completed ? icon("check") : ""}</div>
      <h3>${e(item.title)}</h3><p>${e(item.explanation)}</p>
    </div>`;
  }).join("");
  const hasHumanEdit = state.events.some((event) => event.type === "human_edit");
  const preserved = `<div class="preservation-note">${icon("shield")}<div><b>${hasHumanEdit ? "The human edit stays." : "Unrelated fields stay untouched."}</b><p>${e(state.resources.crm.contact)} remains the contact. Only fields named in this plan can change.</p></div></div>`;
  let control;
  if (plan.status === "stale") {
    control = `<div class="applied-note">The underlying state changed. This approval cannot be reused. Preview a fresh plan before continuing.</div><button class="button button-primary plan-button" data-action="prepare" ${busy ? "disabled" : ""}>Review fresh state &rarr;</button>`;
  } else if (plan.status === "applied") {
    control = `<div class="applied-note">Recovery is recorded, not a clean rewind. The original notice is still delivered. Review the correction draft and any blocked items.</div><button class="button button-secondary replan-button" data-action="verify" ${busy ? "disabled" : ""}>Verify current state</button>`;
  } else if (state.mode !== "rehearsal") {
    control = plan.status === "approved"
      ? `<div class="applied-note">Approved. Owning agents must execute through their scoped tools. The browser will not impersonate them.</div><button class="button button-secondary plan-button" data-action="copy-handoff" ${busy ? "disabled" : ""}>Copy agent handoff</button><p class="plan-footnote">Includes this run, exact plan ID, and full fingerprint. No credentials.</p>`
      : `<button class="button button-primary plan-button" data-action="approve" ${busy ? "disabled" : ""}>${busy ? "Working..." : "Approve exact plan"} <span aria-hidden="true">&rarr;</span></button><p class="plan-footnote">Approval only. No service state changes until the owning agents execute.</p>`;
  } else {
    control = `<button class="button button-primary plan-button" data-action="recover" ${busy ? "disabled" : ""}>${busy ? "Working..." : plan.status === "approved" ? "Continue approved recovery" : "Approve & recover"} <span aria-hidden="true">&rarr;</span></button><p class="plan-footnote">Local human approval. Only this exact plan may run.</p>`;
  }
  return `${items}${preserved}<div class="plan-signature"><span>PLAN FINGERPRINT</span><code>${e(plan.digest.slice(0, 16))}</code></div>${control}`;
}

export function renderOutcome(state, evidence) {
  if (!state.plan || !["applied", "stale"].includes(state.plan.status)) return "";
  const blocked = state.actions.some((a) => a.recovery === "pending");
  const checks = evidence?.checks || [];
  return `<div class="outcome-heading">
    <div><span class="overline">VERIFIED AGAINST CURRENT SERVICE STATE</span><h2 id="outcome-title">${blocked ? "Some work still needs a decision." : "Recovered. Not rewritten."}</h2><p>${blocked ? "Newer changes are protected. Unresolved work stays visible."
      : "The incorrect changes are repaired. The delivered notice remains; its correction needs review."}</p></div>
    <button class="button button-secondary button-small" data-action="export">Export evidence <span aria-hidden="true">&darr;</span></button>
  </div>
  <div class="outcome-checks">${checks.map((check) => `<span class="outcome-check ${check.passed ? "" : "warning"}">${icon(check.passed ? "check" : "warning")}${e(({ discount: "CRM discount", invoice: "Invoice state", message: "Correction draft" })[check.kind])} ${check.passed ? "verified" : "unresolved"}</span>`).join("")}${(evidence?.preserved_human_edits || []).map((edit) => `<span class="outcome-check ${edit.passed ? "" : "warning"}">${icon(edit.passed ? "shield" : "warning")}Human ${e(edit.field)} ${edit.passed ? "preserved" : "changed"}</span>`).join("")}<span class="outcome-check warning">${icon("warning")}Original notice cannot be recalled</span></div>`;
}
