# Windows Setup

## Requirements

- Python 3.11+ with the `py` launcher.
- Git to clone the source, or an extracted source archive.
- A browser for the local workspace.
- Switch Console and a supported coding-agent provider for agent-driven workflows.

The application requires no pip or npm installation.

## Start The Workspace

From the repository root in PowerShell:

```powershell
.\start-windows.cmd
```

Open **http://127.0.0.1:8787** and keep the server terminal running.
Use a second terminal for configuration and validation commands.

The launcher is equivalent to:

```powershell
py -3 -m countermand.server
```

Runtime state, generated credentials, and database files are stored in the ignored
`.countermand/` directory. Restarting the server preserves saved runs.

## Scoped Agent Credentials

Start the server once to generate credentials. Then create one private credential
file per role, without printing its values:

```powershell
$keys = Get-Content ".countermand\credentials.json" -Raw | ConvertFrom-Json
foreach ($role in @("sales", "operations")) {
    $scoped = @{}
    $scoped[$role] = $keys.$role
    $scoped | ConvertTo-Json | Set-Content ".countermand\mcp-$role.json" -Encoding UTF8
}
Remove-Variable keys, scoped
py -3 -m countermand.doctor
```

The diagnostic prints the Python executable and absolute MCP script paths.
Register each process with its corresponding agent provider. Never pass
`credentials.json` or the human credential to either agent.

For workspace-specific provider configuration and tool permissions, see the
[Switch integration guide](switch/README.md).

## Agent-Driven Recovery

1. Click **Create agent run** and copy its ID into the Switch room.
2. Have Sales apply the synthetic discount, then Operations create the draft invoice
   and deliver its notice to the local test mailbox.
3. Select the external run and save a newer contact through **Human edit**.
4. Have the reviewer call `prepare_recovery`.
5. Inspect the repairs, preserved contact, residuals, and plan fingerprint.
6. Click **Approve exact plan**, then **Copy agent handoff**.
7. Send the handoff to the owning agents. Each calls `recover_owned_actions`
   with the exact plan ID and full digest.
8. Read `verify_recovery` and export evidence.

Previewing freezes new forward work; it does not repair service fields.
Approval alone also changes no service state. The original notice remains
delivered, and its correction remains an unsent draft.

## GitHub Issues Pilot

Use a disposable repository, for example `owner/sandbox-repo`.
Only newly tracked issues are eligible for recovery; existing issues and repository
code are outside the adapter's scope.

1. Create a fine-grained GitHub token restricted to that repository with
   **Issues: Read and write** and **Metadata: Read-only**. Do not grant Contents access.
2. Run the private configuration prompt:

   ```powershell
   .\configure-github.cmd
   ```

3. Enter the exact repository and token. Configuration performs a read-only
   repository check and stores the token in `.countermand/github.json`.
4. Stop the running server with Ctrl+C and enable the pilot:

   ```powershell
   .\start-windows.cmd --github-writes
   ```

5. Open **http://127.0.0.1:8787/github**.
6. Expand **Authorize a new workflow**, enter its intent and one to three issue
   titles, and confirm the exact repository name.
7. For the UI pilot, click **Create planned issues manually**. This is a real GitHub write.
8. Add a comment or edit one of those issues directly on GitHub.
9. Preview recovery, inspect which issues are preserved, and acknowledge the
   non-atomic limitation.
10. Click **Approve exact plan only**, then **Execute approved recovery manually**.
11. Refresh from GitHub, verify the resulting issue states, and export evidence.

For agent execution, use the same authorized run with the executor and reviewer
[GitHub briefs](switch/README.md#agent-briefs) instead of the manual creation and
execution buttons. Both paths use the same backend controls.

**Safety:** pause concurrent edits during execution. Rechecks and `If-Match`
headers are not an atomic recovery guarantee. If creation or closure is uncertain,
stop and inspect the recorded links and run markers; do not retry blindly.
Closing issues retains their history.

## Validation

Run the unit suite and local diagnostics:

```powershell
.\check-windows.cmd
```

Browser checks additionally require Node 22+ and Chrome:

```powershell
$env:CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:PYTHON = (py -3 -c "import sys; print(sys.executable)")
node tests/browser.mjs
```

Adjust `CHROME_PATH` to the installed browser location. Browser checks use temporary
state and an in-memory GitHub provider; they perform no real GitHub writes.

## Operating Boundaries

- Keep the server bound to loopback; do not expose it publicly.
- Restrict access to local credential files with appropriate NTFS permissions.
  Unix mode bits are not an NTFS access-control boundary.
- Never place tokens in room messages, browser forms, source files, or exported examples.
- Evidence exports include workflow content. Review them before publishing.
- Approval belongs to the local UI, not to a chat message or a verified Switch identity.

See [SECURITY.md](SECURITY.md) for the complete security model.
