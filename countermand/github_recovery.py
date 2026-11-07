"""Conservative recovery pilot; GitHub atomic write guarantees are not assumed."""

import hashlib
import json
import secrets

from .github_client import fingerprint
from .github_workflow import GitHubWorkflow
from .recovery import StalePlan
from .store import encode, identifier, now


class GitHubRecovery(GitHubWorkflow):
    def prepare(self, run_id):
        with self.lock:
            state = self.inspect(run_id)
            if len(state["actions"]) != len(state["tasks"]) or any(
                a["status"] != "recorded" or a["recovery"] in ("closing", "unknown")
                for a in state["actions"]
            ):
                raise ValueError("All authorized issue receipts must be known before recovery. "
                                 "An uncertain write requires manual investigation.")
            items = []
            for action in state["actions"]:
                current = action["observed"]
                classification = self.classify(action, current)
                items.append({
                    "action_id": action["id"], "number": action["number"],
                    "url": action["url"], "title": current["title"],
                    "classification": classification, "expected": fingerprint(current),
                    "observed": current,
                    "reason": {
                        "close": "Unchanged since this run created it. Propose closing, not deleting.",
                        "preserve": "Changed since creation. Preserve newer work; ask the owner before closing.",
                        "blocked": "Identity mismatch. Do not touch.",
                        "already_closed": "Already closed outside this recovery. No write needed.",
                        "completed": "Previously closed by this recovery. No repeat write.",
                        "changed": "Changed after a previous recovery. Request a human decision.",
                    }[classification],
                })
            body = {
                "id": identifier("ghplan"), "run_id": run_id, "repo": state["repo"],
                "created_at": now(), "items": items, "limitation": self.status()["limitation"],
                "residuals": [
                    "Closing an issue does not erase its history or undo an announcement.",
                    "Preserved issues and announcement corrections need human review.",
                    "This pilot is single-process and does not guarantee atomic GitHub recovery.",
                ],
            }
            digest = hashlib.sha256(encode(body).encode()).hexdigest()
            with self.transaction() as db:
                db.execute("INSERT INTO gh_plans VALUES (?,?,?,?,?,?,?)", (
                    body["id"], run_id, digest, encode(body), "draft", None, None,
                ))
                self.log(db, run_id, "operations", "Recovery reviewed",
                         "Current GitHub state classified; changed issues will be preserved.")
            return self.snapshot(run_id)

    def load_plan(self, plan_id, digest):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM gh_plans WHERE id=?", (plan_id,)).fetchone()
            if not row or not isinstance(digest, str) or not secrets.compare_digest(row["digest"], digest):
                raise ValueError("The exact stored GitHub plan and digest are required")
            body = json.loads(row["body"])
            self.run(db, body["run_id"])
            return dict(row), body

    def mark(self, plan_id, run_id, status, detail):
        with self.transaction() as db:
            db.execute("UPDATE gh_plans SET status=? WHERE id=?", (status, plan_id))
            self.log(db, run_id, "recovery", "Recovery requires review", detail)

    def check_current(self, body):
        state = self.snapshot(body["run_id"])
        actions = {a["id"]: a for a in state["actions"]}
        for item in body["items"]:
            action = actions[item["action_id"]]
            if action["recovery"] == "closed":
                continue
            if action["recovery"] in ("closing", "unknown"):
                raise ValueError("An earlier close has an uncertain outcome. Inspect it manually.")
            current, _ = self.client.get_issue(item["number"])
            if fingerprint(current) != item["expected"]:
                self.mark(body["id"], body["run_id"], "stale",
                          f"Issue #{item['number']} changed. No further issues will be closed.")
                raise StalePlan("GitHub state changed. Review and approve a fresh plan.")

    def approve(self, plan_id, digest, actor, acknowledge_nonatomic=False):
        with self.lock:
            plan, body = self.load_plan(plan_id, digest)
            if actor != "human":
                raise PermissionError("Only the local human can approve this pilot")
            if acknowledge_nonatomic is not True:
                raise ValueError("Acknowledge the non-atomic GitHub limitation before approval")
            if plan["status"] not in ("draft", "approved", "applied"):
                raise StalePlan("Prepare a fresh GitHub plan")
            if plan["status"] == "draft":
                self.check_current(body)
                with self.transaction() as db:
                    db.execute(
                        "UPDATE gh_plans SET status='approved',approved_by=?,approved_at=? WHERE id=?",
                        ("local-human/non-atomic-risk-acknowledged", now(), plan_id),
                    )
                    self.log(db, body["run_id"], actor, "Exact GitHub plan approved",
                             f"Fingerprint {digest[:16]}; best-effort recheck limitation acknowledged.")
            return self.snapshot(body["run_id"])

    def execute(self, plan_id, digest, actor):
        self.require_writes()
        if actor not in ("sales", "human"):
            raise PermissionError("Only the GitHub-owning executor may close tracked issues")
        with self.lock:
            plan, body = self.load_plan(plan_id, digest)
            if plan["status"] not in ("approved", "applied"):
                raise ValueError("The exact GitHub plan needs human approval")
            if plan["status"] == "applied":
                return self.inspect(body["run_id"])
            self.check_current(body)
            for item in body["items"]:
                if item["classification"] != "close":
                    continue
                state = self.snapshot(body["run_id"])
                action = next(a for a in state["actions"] if a["id"] == item["action_id"])
                if action["recovery"] == "closed":
                    continue
                current, etag = self.client.get_issue(item["number"])
                if fingerprint(current) != item["expected"]:
                    self.mark(plan_id, body["run_id"], "stale",
                              f"New change on issue #{item['number']}; remaining writes stopped.")
                    raise StalePlan("An issue changed immediately before closing. Review again.")
                with self.transaction() as db:
                    db.execute("UPDATE gh_actions SET recovery='closing' WHERE id=?",
                               (item["action_id"],))
                try:
                    result = self.client.close_issue(item["number"], etag)
                    verified, _ = self.client.get_issue(item["number"])
                    if (result.get("id") != current["id"] or verified.get("id") != current["id"]
                            or verified.get("state") != "closed"):
                        raise ValueError("GitHub did not verify the expected closed issue")
                    protected = ("title", "body", "comments", "labels", "assignees", "milestone")
                    if any(verified.get(k) != current.get(k) for k in protected):
                        raise ValueError("Concurrent content change detected after closing. "
                                         "Manual review required; no automatic reopen.")
                except (ValueError, OSError, TimeoutError):
                    with self.transaction() as db:
                        db.execute("UPDATE gh_actions SET recovery='unknown' WHERE id=?",
                                   (item["action_id"],))
                    self.mark(plan_id, body["run_id"], "uncertain",
                              f"Close outcome for issue #{item['number']} needs manual inspection.")
                    raise
                with self.transaction() as db:
                    db.execute("UPDATE gh_actions SET recovery='closed',observed=? WHERE id=?",
                               (encode(verified), item["action_id"]))
                    self.log(db, body["run_id"], actor, f"Closed tracked issue #{item['number']}",
                             "Rechecked before the write and verified afterward. History retained.")
            with self.transaction() as db:
                db.execute("UPDATE gh_plans SET status='applied' WHERE id=?", (plan_id,))
                self.log(db, body["run_id"], "recovery", "Bounded recovery finished",
                         "Changed issues were not closed. Announcements cannot be unobserved.")
            return self.inspect(body["run_id"])

    def evidence(self, run_id):
        state = self.inspect(run_id)
        items = state["plan"]["body"]["items"] if state["plan"] else []
        actions = {a["id"]: a for a in state["actions"]}
        checks = []
        for item in items:
            action = actions[item["action_id"]]
            current = action["observed"]
            classification = item["classification"]
            if classification in ("close", "completed"):
                passed = action["recovery"] == "closed" and current["state"] == "closed"
            elif classification in ("preserve", "changed", "blocked"):
                passed = current["state"] == item["observed"]["state"]
            else:
                passed = current["state"] == "closed"
            checks.append({
                "number": item["number"], "classification": classification,
                "passed": passed, "current_state": current["state"], "url": item["url"],
            })
        return {
            "workflow": state,
            "verification": {
                "checked_at": now(), "checks": checks,
                "fully_reversed": False, "atomic_recovery_guaranteed": False,
                "switch_connected": None, "switch_status": "not_monitored",
                "residuals": state["plan"]["body"]["residuals"] if state["plan"] else [],
            },
        }
