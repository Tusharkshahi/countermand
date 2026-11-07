# Security Model

Countermand is a local recovery prototype for instrumented agent workflows.
It is not a multi-tenant service, an OS sandbox, or a production approval system.

## Trust Boundaries

- The web server and adapter clients accept loopback connections only.
- API requests use role-specific bearer credentials or the local browser session.
- Browser mutations require an allowed origin. Session cookies are HttpOnly and SameSite=Strict.
- The browser represents a trusted local human; there is no remote user login.
- Approval is bound to a stored plan and its complete SHA-256 digest.
- Agent tools cannot approve plans. Selecting a role on the command line does not
  override the server-side credential checks.

API scopes do not isolate processes that share an OS account. Code with access to
local files or the browser can bypass the assumptions of a cooperative-agent demo.
Separate workspaces and natural-language instructions are not security boundaries.

## Credential Handling

The server generates separate Sales, Operations, and human credentials in
`.countermand/credentials.json`. Create role-only files for agent processes.
Never give an agent the human key or the combined credential file.

GitHub credentials belong in the private configuration prompt or the server's
environment. Restrict the token to one disposable repository with Issues read/write
and Metadata read permissions; Contents permission is unnecessary.

Keep `.countermand/`, dotenv files, databases, logs, and browser profiles out of
version control. File mode restrictions are not equivalent to Windows NTFS ACLs;
use appropriate OS access controls. Revoke any exposed credentials.

## Recovery Guarantees

Synthetic adapters check targeted field values and versions within a SQLite
transaction. Unrelated fields remain untouched. Conflicting or stale plans require
review; preparing recovery freezes new forward actions in that run.

GitHub operations use best-effort rechecks, optional `If-Match` headers, and
post-write verification. They do not provide an atomic compare-and-close guarantee.
Concurrent edits can race with a close. Pause collaborators during execution and
inspect uncertain outcomes manually rather than retrying or automatically reopening.

The journal is persistent but not tamper-proof. It does not establish independent
provenance, distributed atomicity, or a verified identity bridge from Switch.

## Data And Deployment

Do not expose the server publicly or use production customer data. Synthetic
mailbox delivery never sends external email. A correction draft does not erase
the original notice.

Evidence exports exclude generated adapter credentials but include workflow
content, issue metadata, and audit events. Inspect exports and screenshots before
sharing them, especially when using private repositories.

## Reporting A Vulnerability

Use the repository's private vulnerability reporting channel if available.
Otherwise, open an issue requesting a private contact route without posting
exploit details, credentials, or sensitive workflow data.
