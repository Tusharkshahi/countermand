# Countermand

**Recover what your agents changed. Keep what happened after.**

Countermand is a conflict-aware recovery layer for AI-agent workflows. It records
actions, proposes bounded repairs, requires approval of an exact plan, and verifies
the result without blindly overwriting newer work.

## The Problem

Your agents apply a discount, create an invoice, and deliver a notice. Then you
discover the instruction was wrong. Meanwhile, a teammate has updated the customer.

A blind rollback destroys newer work. A successful tool response does not prove
the consequences were repaired. And a delivered message cannot become unread.

Countermand makes the distinction explicit: **restore what is safe, compensate
what needs a different action, preserve newer work, and expose what remains.**

![Countermand local recovery: discount restored, invoice voided, Maya's edit preserved, and the delivered notice still visible](docs/recovery-workspace.png)

*The recovery workspace, using synthetic CRM, billing, and mailbox data.*

## Capabilities

- **Action receipts:** persistent before/after values, ownership, and field versions.
- **Exact-plan approval:** human authorization bound to a stored plan and SHA-256 digest.
- **Conflict-aware recovery:** preserve unrelated edits and block conflicting repairs.
- **Scoped agent tools:** separate Sales and Operations write permissions through MCP.
- **Evidence export:** current-state checks, recovery outcomes, and unresolved consequences.
- **GitHub Issues pilot:** an opt-in, repository-scoped workflow that preserves changed issues.

## Quick Start

Requirements: **Python 3.11+** and a browser. Git is needed to clone the repository.
The application uses the Python standard library; no package installation is required.

### Windows

```powershell
git clone https://github.com/Tusharkshahi/countermand.git
cd countermand
.\start-windows.cmd
```

### Python CLI

```sh
git clone https://github.com/Tusharkshahi/countermand.git
cd countermand
python -m countermand.server
```

Open **http://127.0.0.1:8787**.

Run this from the repository root. The server binds only to loopback and stores
state and generated credentials in the ignored `.countermand/` directory.

Keep the terminal running while using the UI or agent tools. For launcher commands,
configuration, and browser-test setup, see the [Windows guide](WINDOWS.md).

## Local Demo

Run the complete recovery scenario without an agent account:

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

### Recovery Outcomes

| Consequence | Recovery behavior |
| --- | --- |
| Incorrect 30% discount | Restore the recorded original 3%, if the targeted field is unchanged |
| Incorrect $700 draft invoice | Mark void; preserve its history |
| Maya's newer contact edit | Preserve; recovery never writes that field |
| Human changes the discount to 12% | Refuse to overwrite it; flag a human decision |
| Delivered local notice | Leave delivered; prepare a separate correction draft |
| State changes after preview | Refuse stale approval/execution; require a fresh plan |
| Recovery is retried | Do not repeat completed compensations |

The correction is not sent, and a replacement invoice is not automatically issued.
Those are new decisions, not hidden parts of an "undo everything" button.

## Architecture

Switch is the collaboration surface for the live-agent workflow: the human's
request, scoped agent handoff, recovery discussion, and verification report.
Countermand is the deterministic tool and evidence layer, not a second chatbot.

```text
Human + agents in a Switch room (Slack / Mattermost)
       |
       +-- Executor / Sales MCP ------ CRM discount operations
       |
       +-- Reviewer / Operations MCP - invoice, mailbox, verification
                         |
                  Countermand local API
                         |
              SQLite receipts + recovery engine
                         |
                Web UI / exact-plan review
```

The two adapters have different write scopes. Operations owns its service repairs
and verifies the overall result; it is not an isolated third-party verifier.

### Switch Workflow

1. Register two agents in a Switch room and configure their separate role-scoped MCP clients.
2. Click **Create agent run** and share its ID in the room. Creating a run executes no adapter actions.
3. Sales applies the discount; Operations creates the invoice and local notice.
4. Add a human edit, then request a recovery proposal.
5. Review and **Approve exact plan** in the UI. Approval alone changes no service state.
6. Return the copied plan handoff to the room. Each agent executes only its owned repairs.
7. Verify the resulting state and export evidence.

Local rehearsal mode provides a combined **Approve & recover** convenience.
Externally driven runs require owner-scoped execution; the browser cannot impersonate
the owning adapters. Chat messages do not grant backend approval.

See the [Switch integration guide](switch/README.md) for credential setup,
provider configuration, tool permissions, and agent briefs.

## Safety Model

The backend enforces approval and scope; it does not delegate them to the model:

- Local repairs check targeted values **and field versions** in a SQLite transaction.
- Unrelated edits survive; conflicting or stale plans require renewed review.
- Previewing recovery freezes new forward actions, while receipt retries remain idempotent.
- Agents cannot approve plans or execute another owner's repairs.
- Delivered history remains visible, including any unsent correction draft.

Countermand is a **local prototype**. CRM, billing, and mailbox adapters are synthetic;
their transactional guarantees do not extend to external services. Approval is local,
not a verified Switch identity decision. The journal is persistent, not tamper-proof,
and role instructions are not OS isolation. Keep the server on loopback and avoid
production data. See [SECURITY.md](SECURITY.md) for the complete operating boundaries.

## Optional GitHub Pilot

The `/github` workspace accepts a workflow intent and **one to three actual task
definitions**. A human authorizes this immutable manifest before the executor can
create its marked issues. Agents cannot rewrite task definitions or invent extra slots.
Recovery proposes closing untouched tracked issues and preserving changed ones.
It does not edit code, delete issues, or recover untracked existing issues.

**Writes are disabled by default.** Configuration requires a repository-scoped
Issues token, `--github-writes`, and explicit run authorization. See
[GitHub setup](WINDOWS.md#github-issues-pilot).

To exercise the UI pilot:

1. Authorize a manifest, then click **Create planned issues manually**.
2. Add a comment or edit one created issue directly in GitHub.
3. Click **Preview recovery**. The changed issue should be preserved.
4. Acknowledge the non-atomic limitation and **Approve exact plan only**.
5. Click **Execute approved recovery manually**, refresh, and export evidence.

The UI pilot and MCP tools use the same backend. Manual UI execution is distinct
from agent execution through Switch.

This pilot rechecks state before closing and verifies afterward, but has **no
atomic compare-and-close guarantee**. Pause concurrent edits during recovery.
If a write has an uncertain outcome, stop and inspect GitHub; do not retry it
or create another run to conceal the uncertainty.

## Tests

```powershell
.\check-windows.cmd
```

Or run the Python suite directly:

```sh
python -m unittest discover -s tests -v
```

Optional JavaScript syntax checks require Node:

```sh
node --check web/app.js
node --check web/view.js
node --check web/github.js
```

The suite covers role authorization, approval boundaries, stale plans, field conflicts,
idempotency, partial recovery, GitHub receipts, and uncertain-write handling.

### Browser Checks

Requires Node 22+ and an existing Chrome installation. Set `CHROME_PATH` to the
browser executable and `PYTHON` to the Python executable, then run:

```sh
node tests/browser.mjs
```

Browser checks cover desktop and mobile layouts, rehearsal and external-run
controls, GitHub manifests, preservation, persistence, and evidence export. They
use an isolated server, temporary state, a fresh browser profile, and an in-memory
GitHub provider. Automated tests make no real GitHub mutations.

Screenshots are saved under `.countermand/browser-tests/`. The
[Windows guide](WINDOWS.md#validation) includes ready-to-run commands.

## Repository Layout

| Path | Responsibility |
| --- | --- |
| `countermand/` | Journal, adapters, recovery engine, HTTP API, and scoped MCP tools |
| `web/` | Dependency-free recovery workspace and GitHub pilot UI |
| `switch/` | Integration instructions and role-specific agent briefs |
| `tests/` | Recovery, authorization, transport, packaging, and browser checks |
| `docs/` | Workspace screenshot |

## Documentation

- [Windows setup and GitHub pilot](WINDOWS.md)
- [Switch integration and MCP tools](switch/README.md)
- [Security and operating boundaries](SECURITY.md)
- [Switch quickstart](https://docs.switchagents.ai/switch-rooms/getting-started)
