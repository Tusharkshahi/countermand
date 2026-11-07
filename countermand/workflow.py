"""Three bounded adapters; no production systems or real mail are connected."""

import json

from .store import Store, encode, identifier, now


OWNERS = {"discount": "sales", "invoice": "operations", "message": "operations"}
RESOURCE = {"discount": "crm", "invoice": "billing", "message": "mail"}


class Workflow(Store):
    def create_run(self, mode="rehearsal"):
        if mode not in ("rehearsal", "switch"):
            raise ValueError("Unsupported run mode")
        run_id = identifier("run")
        initial = {
            "crm": {"company": "Acme Studio", "discount": 3,
                    "contact": "Nora Ellis", "email": "nora@example.test"},
            "billing": {"status": "not_created", "amount_cents": 0,
                        "discount": 0, "currency": "USD"},
            "mail": {"status": "not_sent", "body": "",
                     "correction_status": "none", "correction_body": ""},
        }
        with self.transaction() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?)", (
                run_id, now(), mode,
                "Onboard Acme Studio with a discount and prepare its billing.",
            ))
            for kind, data in initial.items():
                db.execute("INSERT INTO resources VALUES (?,?,?,?)", (
                    run_id, kind, encode(data), encode({k: 0 for k in data}),
                ))
            self.event(db, run_id, "human", "created", "Workspace opened",
                       "Synthetic customer data. No live billing or email.")
        return run_id

    def forward(self, run_id, kind, actor):
        if kind not in OWNERS or OWNERS[kind] != actor:
            raise PermissionError("This adapter does not own that action")
        with self.transaction() as db:
            exists = db.execute(
                "SELECT id FROM actions WHERE run_id=? AND kind=?", (run_id, kind),
            ).fetchone()
            if exists:
                return exists["id"]
            if kind == "discount":
                updates, label = {"discount": 30}, "Applied a 30% discount"
            elif kind == "invoice":
                discount_receipt = db.execute(
                    "SELECT changes FROM actions WHERE run_id=? AND kind='discount'",
                    (run_id,),
                ).fetchone()
                if not discount_receipt:
                    raise ValueError("Apply the discount before creating an invoice")
                discount = json.loads(discount_receipt["changes"])["discount"]["after"]
                updates = {"status": "draft", "discount": discount,
                           "amount_cents": 100_000 * (100 - discount) // 100}
                label = "Created the discounted invoice"
            else:
                invoice, _ = self.resource(db, run_id, "billing")
                if invoice["status"] != "draft":
                    raise ValueError("Create a draft invoice before delivering its notice")
                updates = {
                    "status": "delivered",
                    "body": f"Your {invoice['discount']}% discount has been applied. "
                            f"Your draft invoice is ${invoice['amount_cents'] / 100:,.2f}.",
                }
                label = "Delivered the notice to the test mailbox"
            changes = self.change(db, run_id, RESOURCE[kind], updates)
            action_id = identifier("act")
            db.execute(
                "INSERT INTO actions(id,run_id,owner,kind,label,changes,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (action_id, run_id, actor, kind, label, encode(changes), now()),
            )
            self.event(db, run_id, actor, "action", label,
                       "Receipt recorded with field versions and before/after values.")
            return action_id

    def human_edit(self, run_id, field, value):
        if field not in ("contact", "discount"):
            raise ValueError("Only the demo contact and discount fields are editable")
        if field == "discount" and (type(value) is not int or not 0 <= value <= 100):
            raise ValueError("Discount must be a whole number from 0 to 100")
        if field == "contact" and (not isinstance(value, str) or not value.strip()
                                   or len(value) > 100):
            raise ValueError("Contact must contain between 1 and 100 characters")
        with self.transaction() as db:
            receipt = self.change(db, run_id, "crm", {field: value})
            db.execute(
                "INSERT INTO human_edits(run_id,field,receipt,created_at) VALUES (?,?,?,?)",
                (run_id, field, encode(receipt[field]), now()),
            )
            self.event(db, run_id, "Maya", "human_edit",
                       "Maya updated the customer",
                       f"Set {field} to {value}. This edit is outside the agent workflow.")

    def snapshot(self, run_id):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("Workflow not found")
            result = dict(row)
            result["resources"] = {
                kind: self.resource(db, run_id, kind)[0]
                for kind in ("crm", "billing", "mail")
            }
            result["resource_versions"] = {
                kind: self.resource(db, run_id, kind)[1]
                for kind in ("crm", "billing", "mail")
            }
            actions = db.execute(
                "SELECT * FROM actions WHERE run_id=? ORDER BY rowid", (run_id,),
            ).fetchall()
            result["actions"] = [
                {**dict(a), "changes": json.loads(a["changes"])} for a in actions
            ]
            result["events"] = [dict(e) for e in db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,),
            )]
            result["human_edits"] = [
                {**dict(edit), "receipt": json.loads(edit["receipt"])}
                for edit in db.execute(
                    "SELECT * FROM human_edits WHERE run_id=? ORDER BY seq", (run_id,),
                )
            ]
            plan = db.execute(
                "SELECT * FROM plans WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            result["plan"] = {**dict(plan), "body": json.loads(plan["body"])} if plan else None
            return result

    def list_runs(self):
        with self.transaction() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,created_at,mode FROM runs ORDER BY rowid DESC",
            )]
