"""Approved, version-checked compensations for the explicitly supported actions."""

import hashlib
import json
import secrets

from .store import encode, identifier, now
from .workflow import RESOURCE, Workflow


class StalePlan(ValueError):
    pass


class Recovery(Workflow):
    def prepare(self, run_id):
        with self.transaction() as db:
            actions = db.execute(
                "SELECT * FROM actions WHERE run_id=? ORDER BY rowid DESC", (run_id,),
            ).fetchall()
            if not actions:
                raise ValueError("Run the workflow before preparing its recovery")
            items = []
            original_discount = next((
                json.loads(a["changes"])["discount"]["before"]
                for a in actions if a["kind"] == "discount"
            ), 3)
            for action in actions:
                kind = action["kind"]
                changes = json.loads(action["changes"])
                data, versions = self.resource(db, run_id, RESOURCE[kind])
                checks = {
                    field: {"value": data[field], "version": versions[field]}
                    for field in changes
                }
                conflict = any(
                    data[field] != change["after"] or versions[field] != change["version"]
                    for field, change in changes.items()
                )
                item = {
                    "action_id": action["id"], "owner": action["owner"], "kind": kind,
                    "checks": checks, "updates": {}, "state": "ready",
                    "result": {"discount": "restored", "invoice": "compensated",
                               "message": "mitigated"}[kind],
                }
                if kind == "discount":
                    item.update(
                        title=f"Restore the discount to {original_discount}%",
                        explanation="Restore only the field this workflow changed.",
                        updates={"discount": original_discount}, classification="restore",
                    )
                elif kind == "invoice":
                    item.update(
                        title="Void the incorrect draft invoice",
                        explanation="Keep the invoice and its history; mark it void.",
                        updates={"status": "void"}, classification="compensate",
                    )
                else:
                    item.update(
                        title="Prepare a correction for review",
                        explanation="The original notice remains delivered. "
                                    "A correction is a new draft, not an unsend.",
                        updates={"correction_status": "draft",
                                 "correction_body":
                                     "Correction: our previous discount notice was "
                                     f"incorrect. The agreed discount was {original_discount}%. "
                                     "Please disregard the earlier draft invoice. "
                                     "A replacement invoice still needs review."},
                        classification="repair",
                    )
                    for field in ("correction_status", "correction_body"):
                        item["checks"][field] = {
                            "value": data[field], "version": versions[field],
                        }
                    if data["correction_status"] != "none":
                        conflict = True
                if action["recovery"] != "pending":
                    item.update(state="completed", explanation="Already processed; no new action.")
                elif conflict:
                    item.update(state="blocked", explanation="A targeted field changed after "
                                "the original action. Preserve it and request a human decision.")
                items.append(item)
            contact, versions = self.resource(db, run_id, "crm")
            body = {
                "id": identifier("plan"), "run_id": run_id, "created_at": now(),
                "intent": "Recover the incorrect discount workflow without overwriting newer work.",
                "items": items,
                "preserved": [{
                    "field": "contact", "value": contact["contact"],
                    "reason": "Not changed by the original workflow. Recovery never writes it.",
                    "edited": versions["contact"] > 0,
                }],
                "residuals": ["The original email remains in the test mailbox.",
                              "A replacement invoice and sending any correction require new review."]
                if any(a["kind"] == "message" for a in actions) else [],
            }
            digest = hashlib.sha256(encode(body).encode()).hexdigest()
            db.execute("INSERT INTO plans VALUES (?,?,?,?,?,?,?)", (
                body["id"], run_id, digest, encode(body), "draft", None, None,
            ))
            self.event(db, run_id, "recovery", "plan", "Recovery plan prepared",
                       "Exact operations and field versions are bound to this plan.")
        return self.snapshot(run_id)

    @staticmethod
    def _load_plan(db, plan_id, digest):
        plan = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not plan:
            raise ValueError("Recovery plan not found")
        if not isinstance(digest, str) or not secrets.compare_digest(plan["digest"], digest):
            raise ValueError("The approval digest does not match the stored plan")
        return plan, json.loads(plan["body"])

    def _is_current(self, db, body):
        for item in body["items"]:
            action = db.execute(
                "SELECT recovery FROM actions WHERE id=?", (item["action_id"],),
            ).fetchone()
            if item["state"] == "completed" or action["recovery"] != "pending":
                continue
            data, versions = self.resource(db, body["run_id"], RESOURCE[item["kind"]])
            if any(data[field] != check["value"] or versions[field] != check["version"]
                   for field, check in item["checks"].items()):
                return False
        return True

    def _mark_stale(self, db, plan_id, run_id):
        db.execute("UPDATE plans SET status='stale' WHERE id=?", (plan_id,))
        self.event(db, run_id, "recovery", "conflict", "Recovery stopped: state changed",
                   "Nothing further was changed. Prepare and review a fresh plan.")

    def approve(self, plan_id, digest, approver):
        if not isinstance(approver, str) or not approver.strip():
            raise ValueError("An authenticated approver identity is required")
        stale = False
        with self.transaction() as db:
            plan, body = self._load_plan(db, plan_id, digest)
            if plan["status"] not in ("draft", "approved", "applied"):
                raise StalePlan("Prepare a fresh recovery plan")
            if plan["status"] in ("approved", "applied"):
                return body["run_id"]
            if not self._is_current(db, body):
                self._mark_stale(db, plan_id, body["run_id"])
                stale = True
            else:
                db.execute(
                    "UPDATE plans SET status='approved',approved_by=?,approved_at=? WHERE id=?",
                    (approver, now(), plan_id),
                )
                self.event(db, body["run_id"], approver, "approval",
                           "Exact recovery plan approved",
                           f"Approval bound to {digest[:12]}; blocked items are excluded.")
        if stale:
            raise StalePlan("State changed after preview. Review a fresh plan.")
        return body["run_id"]

    def execute(self, plan_id, digest, actor):
        if actor not in ("sales", "operations"):
            raise PermissionError("Only an owning adapter can execute recovery")
        stale = False
        with self.transaction() as db:
            plan, body = self._load_plan(db, plan_id, digest)
            if plan["status"] not in ("approved", "applied"):
                raise ValueError("This exact plan needs human approval before execution")
            if not self._is_current(db, body):
                self._mark_stale(db, plan_id, body["run_id"])
                stale = True
            else:
                for item in body["items"]:
                    if item["owner"] != actor or item["state"] != "ready":
                        continue
                    action = db.execute("SELECT recovery FROM actions WHERE id=?",
                                        (item["action_id"],)).fetchone()
                    if action["recovery"] != "pending":
                        continue
                    self.change(db, body["run_id"], RESOURCE[item["kind"]], item["updates"])
                    db.execute("UPDATE actions SET recovery=? WHERE id=?",
                               (item["result"], item["action_id"]))
                    self.event(db, body["run_id"], actor, "recovery",
                               item["title"], item["explanation"])
                pending_ready = any(
                    i["state"] == "ready" and db.execute(
                        "SELECT recovery FROM actions WHERE id=?", (i["action_id"],),
                    ).fetchone()["recovery"] == "pending"
                    for i in body["items"]
                )
                if not pending_ready:
                    db.execute("UPDATE plans SET status='applied' WHERE id=?", (plan_id,))
        if stale:
            raise StalePlan("State changed after approval. No further recovery was executed.")
        return self.snapshot(body["run_id"])

    def verify(self, run_id):
        snapshot = self.snapshot(run_id)
        resources = snapshot["resources"]
        by_kind = {a["kind"]: a for a in snapshot["actions"]}
        checks = []
        for kind, action in by_kind.items():
            state = action["recovery"]
            if state == "pending":
                checks.append({"kind": kind, "passed": False, "detail": "Not recovered"})
                continue
            if kind == "discount":
                passed = resources["crm"]["discount"] == action["changes"]["discount"]["before"]
            elif kind == "invoice":
                passed = resources["billing"]["status"] == "void"
            else:
                passed = (resources["mail"]["status"] == "delivered"
                          and resources["mail"]["correction_status"] == "draft")
            checks.append({"kind": kind, "passed": passed, "detail": state})
        latest_edits = {edit["field"]: edit for edit in snapshot["human_edits"]}
        crm = resources["crm"]
        versions = snapshot["resource_versions"]["crm"]
        preserved = [{
            "field": field, "expected": edit["receipt"]["after"], "actual": crm[field],
            "passed": (crm[field] == edit["receipt"]["after"]
                       and versions[field] == edit["receipt"]["version"]),
        } for field, edit in latest_edits.items()]
        return {
            "run_id": run_id, "checked_at": now(), "checks": checks,
            "preserved_human_edits": preserved,
            "all_supported_repairs_verified": (
                bool(checks) and all(c["passed"] for c in checks)
                and all(edit["passed"] for edit in preserved)
            ),
            "fully_reversed": False,
            "residuals": snapshot["plan"]["body"]["residuals"] if snapshot["plan"] else [],
            "scope": "Synthetic local adapters only; not production billing or email.",
        }
