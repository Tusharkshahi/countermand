# Switch Integration

Switch coordinates agent requests, addressed handoffs, and recovery reports in a
shared room. Countermand supplies the scoped tools, deterministic recovery logic,
local human approval, and evidence.

## Topology

```text
Human in Switch room
        |
        +-- Sales agent -------- scoped CRM operations
        |
        +-- Operations agent --- scoped draft billing / local mailbox operations
        |
        +-- Countermand UI ----- shared evidence and before/after inspection
```

The MCP processes and Countermand backend must run on the same host because the
adapter API is loopback-only. The Switch room server can be managed separately.

## Prerequisites

- A running Countermand server.
- Switch Console with a connected messaging app, such as Slack or Mattermost.
- A configured coding-agent provider supported by Switch.
- Two agents with separate workspaces and role-specific MCP configurations.

Follow the [Switch quickstart](https://docs.switchagents.ai/switch-rooms/getting-started)
for Console and room setup. Keep the provider's normal permission controls enabled.

## Configure MCP Clients

Countermand implements newline-delimited JSON-RPC over stdio. Start the server
first so it creates `.countermand/credentials.json`, then make two private files:

- `.countermand/mcp-sales.json`, containing only the `sales` key and its token.
- `.countermand/mcp-operations.json`, containing only the `operations` key and its token.

The [Windows setup guide](../WINDOWS.md#scoped-agent-credentials) includes commands
that create these files without printing their contents. Do not pass the combined
credential file or the `human` key to an agent.

Run the diagnostic to obtain the Python executable and absolute script paths:

```sh
python -m countermand.doctor
```

Register a separate stdio server in each agent provider. For a Cursor workspace,
place this structure in that workspace's `.cursor/mcp.json`, replacing the paths
with the diagnostic output:

```json
{
  "mcpServers": {
    "countermand": {
      "type": "stdio",
      "command": "<absolute-python-executable>",
      "args": [
        "<project>/countermand/mcp.py",
        "--role", "sales",
        "--credential-file", "<project>/.countermand/mcp-sales.json"
      ]
    }
  }
}
```

For Operations, use `--role operations` and `mcp-operations.json` in its own
workspace. Do not register both role credentials globally or in a shared workspace.
Other providers can register the same command and arguments using their stdio
MCP configuration format.

Alternatively, omit `--credential-file` and supply only the selected role's token
through `COUNTERMAND_ADAPTER_TOKEN` in that process's private environment.

For Cursor, enable the server from each workspace:

```sh
agent mcp enable countermand
agent mcp list-tools countermand
```

Restart an existing agent session after changing its provider configuration.
Tool discovery confirms process startup; use `inspect_workflow` on an existing
run to check authenticated backend access.

## Tool Permissions

| Tool | Sales | Operations |
| --- | --- | --- |
| `inspect_workflow` | Yes | Yes |
| `prepare_recovery` | Yes | Yes |
| `recover_owned_actions` | Own actions only | Own actions only |
| `verify_recovery` | Yes | Yes |
| `apply_demo_discount` | Yes | No |
| `create_demo_invoice` | No | Yes |
| `deliver_demo_notice` | No | Yes |
| `inspect_github_run` | Yes | Yes |
| `verify_github_recovery` | Yes | Yes |
| `create_github_issue` | Yes | No |
| `recover_github_issues` | Yes | No |
| `prepare_github_recovery` | No | Yes |

There is deliberately no approval tool. The server checks credentials independently
of a process's declared role, so selecting `--role operations` while holding a
Sales token does not grant Operations access.

## Run The Recovery Scenario

1. Invite both agents to one room and allow addressed handoffs.
2. Click **Create agent run** in Countermand and share the exact run ID.
3. Ask Sales to inspect the run and call `apply_demo_discount`.
4. Have Sales address Operations with the same ID. Operations calls
   `create_demo_invoice`, then `deliver_demo_notice`, and stops.
5. Save a newer contact using **Human edit** in the UI.
6. Ask Operations to call `prepare_recovery` and report the plan ID, full digest,
   repairs, preserved work, and residual consequences.
7. Review and **Approve exact plan** locally, then copy the handoff into the room.
8. Have each owner call `recover_owned_actions` for that plan and digest.
9. Call `verify_recovery`, inspect current state, and export evidence.

Preparing recovery freezes new forward actions. A newer conflicting discount
blocks its repair; an unrelated contact edit stays untouched. State changes after
preview require a fresh plan and approval.

## Agent Briefs

- [Sales / synthetic CRM](sales.md)
- [Operations / draft billing and mailbox](operations.md)
- [GitHub executor](github-executor.md)
- [GitHub reviewer](github-reviewer.md)

For GitHub, authorize the manifest in `/github` first. The executor creates only
the authorized slots. On a recovery request, the reviewer proposes a plan, the
human approves it locally, and the executor performs the approved closures.
The separate manual UI pilot does not require agent execution.

## Approval And Observability

Approval is local to Countermand's UI, not an authenticated Switch or Slack
identity decision. Room messages alone cannot authorize backend execution.
The combined **Approve & recover** button is restricted to local rehearsal mode.

Countermand does not probe Switch liveness. `/health` reports
`switch_connected: null` and `switch_status: "not_monitored"`. External-run labels
and action receipts describe backend activity, not the transport that produced it.

Roles and separate directories are not OS sandboxes. Keep credential files private,
avoid shared/global role configuration, and do not rely on dialogue as the only
evidence of an action. See [SECURITY.md](../SECURITY.md) and Switch's
[shared-responsibility guide](https://docs.switchagents.ai/switch-rooms/resources/shared-responsibility).
