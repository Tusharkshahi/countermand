# Switch Handoff

## Implemented Versus Pending

Implemented: a working local domain, field-versioned receipts, exact-plan approval,
and scoped MCP tools that call the same tested HTTP API used by the rehearsal.

Pending: provider installation/configuration, a real Switch room, agent-to-agent
handoffs, and a verified mapping from a human's Switch identity/approval to the
recovery API. This repository must not be presented as a live Switch integration
until those steps are exercised.

## Intended Topology

```text
Human in Switch room
        |
        +-- Sales agent -------- scoped CRM operations
        |
        +-- Operations agent --- scoped draft billing / local mailbox operations
        |
        +-- Countermand UI ----- shared evidence and before/after inspection
```

Use one room initially. Multi-room routing, automatic agent replacement, and extra
coordinator agents are not needed for this scenario.

## MCP Entry Points

From the repository root:

```sh
python3 -m countermand.mcp --role sales
python3 -m countermand.mcp --role operations
```

Each process requires `COUNTERMAND_ADAPTER_TOKEN`, supplied privately through its
provider's environment. The server creates separate `sales`, `operations`, and
`human` credentials in `.countermand/credentials.json`; use only the selected
adapter's credential. Never put the human credential in either agent's environment.

When configuring a provider that runs outside this directory, use an absolute path
to `countermand/mcp.py` as the Python script argument. Provider-specific setup must
be verified against the provider actually selected; no CLI registration syntax is
assumed here.

These processes implement newline-delimited JSON-RPC stdio MCP. They expose:

| Tool | Sales | Operations |
| --- | --- | --- |
| `inspect_workflow` | Yes | Yes |
| `prepare_recovery` | Yes | Yes |
| `recover_owned_actions` | Own actions only | Own actions only |
| `verify_recovery` | Yes | Yes |
| `apply_demo_discount` | Yes | No |
| `create_demo_invoice` | No | Yes |
| `deliver_demo_notice` | No | Yes |

There is deliberately no approval tool. The server checks credentials independently
of a process's declared role, so selecting `--role operations` while holding a
Sales token does not grant Operations access.

## Live Integration Checklist

1. Install Switch Console and configure a supported coding-agent provider.
2. Get one agent replying in the bundled Mattermost chat.
3. Configure the two MCP clients with their separate role credentials.
4. Add both agents to one private room and permit their addressed handoffs.
5. Create an externally driven run using the local human API with `mode: "switch"`.
   This mode disables browser impersonation of the owning adapters. It is only a
   marker, not proof that Switch is connected.
6. Have Sales perform its action and hand the shared run ID to Operations.
7. Have Operations create the draft and deliver the local test notice.
8. Record a newer human edit and request recovery in the room.
9. Implement/verify the human approval bridge. Bind an authorized Switch user to
   the exact plan ID and digest, authenticate the server-side approval request,
   reject stale state, and keep the human credential away from agent processes.
10. Execute each owner's recovery through its MCP client; inspect and export the
    resulting evidence in the UI.
11. Run the stale-plan and same-field-conflict cases through the room.
12. Replace the UI's fixed connection notice only after real liveness/provenance
    is available. A tool call alone is not evidence of a Switch connection.

The browser's local **Approve & recover** button is a rehearsal convenience. It
does not stand in for step 9 in the final hackathon story.

## Constraints To Preserve

- Switch roles are instructions, not credential boundaries.
- Shared-room content is visible to the room's members.
- A working directory is not an OS-level sandbox.
- Scope tools and runtime permissions before connecting an agent.
- Freeze the server version and validate its current protocol. Do not assume old
  SSE examples describe the current transport.
- Never let agent dialogue be the only record that an action or approval happened.

Start with the [official quickstart](https://docs.switchagents.ai/switch-rooms/getting-started)
and [shared-responsibility guide](https://docs.switchagents.ai/switch-rooms/resources/shared-responsibility).
