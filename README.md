# Countermand

**Recover what your agents changed. Keep what happened after.**

A minimal recovery workspace for a completed workflow that turns out to be wrong.
It records exact changes, previews bounded compensations, binds approval to a plan,
and checks current field versions before any recovery writes.

**Windows and GitHub pilot:** see [WINDOWS.md](WINDOWS.md). A bounded real-Issues
adapter, separate executor/reviewer tools, and a `/github` workspace are prepared.
Tests use a fake provider; **no live GitHub writes have been performed or verified**.
GitHub recovery is explicitly best-effort, not the atomic local SQLite model.

## Current Status

**Working local rehearsal. Not yet a live Switch submission.**

- Responsive web UI, persistent SQLite state, and JSON evidence export.
- Synthetic CRM, draft-invoice, and mailbox adapters.
- Typed, owner-scoped operations and exact-plan human approval.
- Version checks, protected human edits, retry-safe recovery, and visible residuals.
- Scoped stdio MCP tools ready for provider configuration and integration testing.

Switch Console, a supported agent provider, and a real room have deliberately not
been installed or configured yet. The UI and health endpoint say so. The local
rehearsal uses deterministic adapters, not simulated AI conversations.

## Run

Python 3.11+ is the only application prerequisite. No pip or npm install is needed.

```sh
python3 -m countermand.server
```

Open **http://127.0.0.1:8787**.

Run this from the repository root. The server binds only to loopback and stores
state and generated credentials in the ignored `.countermand/` directory.

If a local browser-preview proxy changes the browser's origin, explicitly allow
that exact loopback origin rather than disabling origin checks:

```sh
python3 -m countermand.server --browser-origin http://127.0.0.1:60571
```

Use your preview's actual port; the example is not a permanent requirement.

## Try The Story

1. Click **Run rehearsal**. A deliberately incorrect 30% discount is recorded,
   a $700 draft invoice is created, and a notice is delivered to a local mailbox.
   The customer's original agreed discount was 3%, on a $1,000 base.
2. Click **Human edit**. Save Maya's newer contact name.
3. Click **Preview recovery**. Inspect the exact operations and plan fingerprint.
4. Click **Approve & recover**. The owning adapters perform only their repairs.
5. Inspect the result: discount restored, draft invoice voided, contact preserved,
   and a correction drafted. The original notice remains delivered.
6. Export evidence to inspect receipts, field versions, approval, and verification.

For a conflict, start a **New rehearsal** and enable **Also change the discount
to 12%** in the human-edit dialog. Recovery preserves that newer discount and leaves
the decision unresolved; other approved repairs can proceed.

To test stale approval through the UI, preview a plan, then add a human edit to
the discount before approving. Approval is refused until a fresh plan is reviewed.
New rehearsals create isolated records; they never delete previous runs.

## Safety Model

The language model is not responsible for enforcing these invariants:

- Mutations use registered operations, not generated SQL or arbitrary shell.
- Sales credentials cannot perform Operations mutations or approve a plan.
- Approval names a stored plan and its SHA-256 digest.
- Each targeted field is checked by value **and version**, including ABA changes.
- Check-and-write happens in a local SQLite transaction.
- Recovery receipts make retries idempotent.
- Changes to unrelated fields do not invalidate safe recovery or get overwritten.
- A delivered notice is never marked unsent. A correction remains a new draft.

The browser is a local human demo identity, not an authenticated production user.
The service credentials grant write scopes; the synthetic evidence ledger is shared.
Do not expose this server to a network or use production data.

## What This Does Not Prove

- The adapters share one local SQLite database. This is **not** a proof of
  cross-service atomicity, distributed rollback, or separate-machine isolation.
- There are no real payments, production invoices, external messages, or SaaS integrations.
- The action journal is persistent, not independently witnessed or tamper-proof.
- Recovery covers instrumented demo operations only.
- No natural-language planner is connected yet. The rehearsal has one fixed scenario.
- Production execution needs per-service conditional writes, durable coordination,
  transport identity, stronger authorization, and service-specific compensation rules.
- A fully recovered local plan can still have irreversible or outstanding consequences.

## Tests

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
node --check web/view.js
```

The optional browser test uses Node 22+ and an existing Chrome installation. It
uses Chrome's DevTools protocol directly; no browser package is downloaded.

```sh
node tests/browser.mjs
```

On platforms other than macOS, set `CHROME_PATH` to the Chrome executable. The test
starts an isolated server on port 8788, uses a fresh browser profile, and saves
screenshots under `.countermand/browser-tests/`. It does not touch your normal
browser profile or the main demo's database.

## Layout

- `countermand/store.py`: persistent resources, field versions, and audit records.
- `countermand/workflow.py`: bounded forward operations and human-edit receipts.
- `countermand/recovery.py`: plan, approval, execution, and current-state verification.
- `countermand/server.py`: loopback web server and authenticated local API.
- `countermand/mcp.py`: role-scoped stdio tools; no human-approval tool.
- `web/`: dependency-free responsive interface.
- `tests/`: engine, authorization, transport, and browser checks.
- `switch/`: agent briefs and the remaining live-integration work.

See [the Switch handoff](switch/README.md) before configuring real agents.
