# Windows Handoff

Python 3.12.5 and Git 2.49 are sufficient for the application. No pip/npm install.
Windows execution has not been verified on this Mac; run the included checks.

## Start With The Working Rehearsal

1. Clone the separate Countermand source repository, or extract its source archive.
   TaskMind is the workflow target, **not** the source repository to overwrite.
2. In the extracted/cloned project folder, run `start-windows.cmd`.
3. Open http://127.0.0.1:8787 and test the local recovery story.
4. Run `check-windows.cmd` to run tests and print provider-launch descriptions.

Terminal equivalents:

```powershell
py -3 -m countermand.server
py -3 -m unittest discover -s tests -v
py -3 -m countermand.doctor
```

## Opt Into Real GitHub Issues

The GitHub pilot is disabled by default and never modifies repository code.
It can create at most three issues in each human-authorized run, and recovery only
considers the exact issue IDs recorded in that run. Existing issues are out of scope.

1. Create a fine-grained GitHub token for **Tusharkshahi/TaskMind only**, with
   Issues read/write and Metadata read permissions. Do not grant Contents access.
2. Run `configure-github.cmd`. It prompts privately, validates the repository with
   a read-only API request, and stores the credential in ignored local state.
3. Stop the server and run `start-windows.cmd --github-writes`.
4. Open http://127.0.0.1:8787/github.
5. Type the exact repository name to authorize a run. Issue creation is a separate,
   explicit step, either through the manual pilot button or the owning agent's tool.
6. Edit one created issue **directly on GitHub** (title or a comment).
7. Preview recovery. The edited issue should say **preserve**.
8. Review and acknowledge the non-atomic limitation before approving the exact plan.
9. Ask the executor to execute, or use the explicitly manual pilot action.

No GitHub writes were performed during preparation on the Mac. Real endpoint
behavior must be exercised on the sandbox before presenting a live demo.

### Important Limits

- Rechecks are not a verified atomic GitHub compare-and-close. Pause collaborators
  during recovery; the UI explicitly requires acknowledgment.
- `If-Match` is sent when an ETag is available, but enforcement is not assumed.
- A timed-out create/close is marked uncertain, not retried automatically.
- On uncertainty, inspect GitHub using the run marker and recorded issue links.
  Do not create replacement runs to hide unknown outcomes.
- Closing is compensation, not deletion or history erasure.
- A local credential file is not an OS sandbox. On Windows, Unix mode bits do not
  establish private NTFS ACLs. Keep local state private and credentials narrowly scoped.
- Never upload `.countermand/`, copy credentials into agent prompts, or expose
  the development server publicly.

## Switch Is Still Required

Slack may be deferred. Switch may not be omitted from the hackathon workflow.

Install the official Windows Console:
https://github.com/sandbox-quantum/switch/releases/latest/download/switch-console-x64.exe

Windows is early access. Set up a local server and use bundled Mattermost if Slack
configuration is taking too long. Follow the installed version's prerequisite checks.

Then:

1. Configure a supported provider. The operator now uses Cursor: verify
   `agent --version`, complete `agent login`, and confirm it is ready in Switch.
   Codex is an alternative, not an application requirement.
2. Get one agent answering in a real Switch room.
3. Run `py -3 -m countermand.doctor` for the two scoped MCP process descriptions.
4. Configure the executor and reviewer separately. Do not give both sets of tools
   to both agents through a shared provider configuration.
5. Use `switch/github-executor.md` and `switch/github-reviewer.md` as briefs.
6. Authorize a GitHub run in the UI, then give its ID to the executor in the room.
7. Have the reviewer prepare the recovery plan and the executor recover only after approval.

The current GitHub pilot uses **local UI human approval**, not a verified Switch
identity bridge. Say that honestly in the demo. A live room and real tool handoffs
must still be tested; tool availability does not prove a Switch connection.
