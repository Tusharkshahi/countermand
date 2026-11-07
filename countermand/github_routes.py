"""Authenticated API boundary for the opt-in real GitHub pilot."""


def get_github(server, parts):
    pilot = server.github
    if parts == ["api", "github", "status"]:
        return 200, pilot.status()
    if parts == ["api", "github", "runs"]:
        return 200, {"runs": pilot.list_runs()}
    if len(parts) == 4 and parts[:3] == ["api", "github", "runs"]:
        return 200, pilot.snapshot(parts[3])
    if len(parts) == 5 and parts[:3] == ["api", "github", "runs"]:
        if parts[4] == "inspect":
            return 200, pilot.inspect(parts[3])
        if parts[4] == "evidence":
            return 200, pilot.evidence(parts[3])
    return None


def post_github(server, parts, body, role):
    pilot = server.github
    if parts == ["api", "github", "runs"]:
        if role != "human":
            raise PermissionError("A human must authorize creation of the new tracked issues")
        return 201, pilot.authorize(body.get("confirmation"), role, body.get("tasks"),
                                    body.get("intent", "Project kickoff"))
    if len(parts) == 5 and parts[:3] == ["api", "github", "runs"]:
        run_id, operation = parts[3:]
        if operation == "issues":
            return 200, pilot.create_issue(run_id, body.get("slot"), role)
        if operation == "plan":
            if role not in ("operations", "human"):
                raise PermissionError("The reviewer, not the executor, prepares the GitHub plan")
            return 201, pilot.prepare(run_id)
    if len(parts) == 5 and parts[:3] == ["api", "github", "plans"]:
        plan_id, operation = parts[3:]
        if operation == "approve":
            return 200, pilot.approve(plan_id, body.get("digest"), role,
                                      body.get("acknowledge_nonatomic"))
        if operation == "execute":
            return 200, pilot.execute(plan_id, body.get("digest"), role)
    return None
