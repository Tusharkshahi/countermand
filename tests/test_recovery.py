import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from countermand.recovery import Recovery, StalePlan


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "state.sqlite3"
        self.engine = Recovery(self.path)
        self.run_id = self.engine.create_run()
        for kind, owner in (("discount", "sales"), ("invoice", "operations"),
                            ("message", "operations")):
            self.engine.forward(self.run_id, kind, owner)

    def tearDown(self):
        self.directory.cleanup()

    def plan(self):
        return self.engine.prepare(self.run_id)["plan"]

    def approve(self, plan):
        return self.engine.approve(plan["id"], plan["digest"], "local-demo-human")

    def recover(self, plan):
        for owner in ("operations", "sales"):
            self.engine.execute(plan["id"], plan["digest"], owner)

    def test_full_recovery_preserves_newer_unrelated_human_edit(self):
        self.engine.human_edit(self.run_id, "contact", "Maya Chen")
        plan = self.plan()
        self.approve(plan)
        self.recover(plan)
        state = self.engine.snapshot(self.run_id)
        self.assertEqual(state["resources"]["crm"]["discount"], 3)
        self.assertEqual(state["resources"]["crm"]["contact"], "Maya Chen")
        self.assertEqual(state["resources"]["billing"]["status"], "void")
        self.assertEqual(state["resources"]["mail"]["status"], "delivered")
        self.assertEqual(state["resources"]["mail"]["correction_status"], "draft")
        self.assertEqual(state["plan"]["status"], "applied")
        evidence = self.engine.verify(self.run_id)
        self.assertTrue(evidence["all_supported_repairs_verified"])
        self.assertTrue(evidence["preserved_human_edits"][0]["passed"])
        self.assertEqual(evidence["preserved_human_edits"][0]["actual"], "Maya Chen")
        self.assertFalse(evidence["fully_reversed"])
        self.assertTrue(evidence["residuals"])

    def test_no_execution_before_approval(self):
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, "human approval"):
            self.recover(plan)
        self.assertEqual(self.engine.snapshot(self.run_id)["resources"]["crm"]["discount"], 30)

    def test_wrong_digest_cannot_approve(self):
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, "digest"):
            self.engine.approve(plan["id"], "0" * 64, "human")

    def test_wrong_digest_cannot_execute(self):
        plan = self.plan()
        self.approve(plan)
        with self.assertRaisesRegex(ValueError, "digest"):
            self.engine.execute(plan["id"], "wrong", "sales")

    def test_change_after_preview_invalidates_approval(self):
        plan = self.plan()
        self.engine.human_edit(self.run_id, "discount", 12)
        with self.assertRaises(StalePlan):
            self.approve(plan)
        self.assertEqual(self.engine.snapshot(self.run_id)["plan"]["status"], "stale")

    def test_change_after_approval_invalidates_execution(self):
        plan = self.plan()
        self.approve(plan)
        self.engine.human_edit(self.run_id, "discount", 12)
        with self.assertRaises(StalePlan):
            self.recover(plan)
        state = self.engine.snapshot(self.run_id)
        self.assertEqual(state["resources"]["crm"]["discount"], 12)
        self.assertEqual(state["resources"]["billing"]["status"], "draft")
        self.assertEqual(state["resources"]["mail"]["correction_status"], "none")

    def test_same_field_conflict_is_preserved_but_other_repairs_can_proceed(self):
        self.engine.human_edit(self.run_id, "discount", 12)
        plan = self.plan()
        discount = next(i for i in plan["body"]["items"] if i["kind"] == "discount")
        self.assertEqual(discount["state"], "blocked")
        self.approve(plan)
        self.recover(plan)
        state = self.engine.snapshot(self.run_id)
        self.assertEqual(state["resources"]["crm"]["discount"], 12)
        self.assertEqual(state["resources"]["billing"]["status"], "void")
        self.assertFalse(self.engine.verify(self.run_id)["all_supported_repairs_verified"])

    def test_aba_change_is_a_conflict_even_when_value_matches(self):
        self.engine.human_edit(self.run_id, "discount", 12)
        self.engine.human_edit(self.run_id, "discount", 30)
        plan = self.plan()
        discount = next(i for i in plan["body"]["items"] if i["kind"] == "discount")
        self.assertEqual(discount["state"], "blocked")

    def test_unrelated_edit_after_approval_does_not_invalidate_plan(self):
        plan = self.plan()
        self.approve(plan)
        self.engine.human_edit(self.run_id, "contact", "A newer contact")
        self.recover(plan)
        self.assertEqual(
            self.engine.snapshot(self.run_id)["resources"]["crm"]["contact"], "A newer contact",
        )

    def test_repeat_execution_does_not_duplicate_repairs_or_receipts(self):
        plan = self.plan()
        self.approve(plan)
        self.recover(plan)
        first = self.engine.snapshot(self.run_id)
        self.recover(plan)
        self.assertEqual(first, self.engine.snapshot(self.run_id))

    def test_owner_cannot_forward_another_owners_action(self):
        other = self.engine.create_run()
        with self.assertRaises(PermissionError):
            self.engine.forward(other, "discount", "operations")

    def test_owner_only_recovers_its_own_actions(self):
        plan = self.plan()
        self.approve(plan)
        self.engine.execute(plan["id"], plan["digest"], "sales")
        state = self.engine.snapshot(self.run_id)
        self.assertEqual(state["resources"]["crm"]["discount"], 3)
        self.assertEqual(state["resources"]["billing"]["status"], "draft")
        self.assertEqual(state["plan"]["status"], "approved")

    def test_unknown_actor_cannot_execute(self):
        plan = self.plan()
        self.approve(plan)
        with self.assertRaises(PermissionError):
            self.engine.execute(plan["id"], plan["digest"], "coordinator")

    def test_restart_preserves_approval_and_recovers(self):
        plan = self.plan()
        self.approve(plan)
        self.engine = Recovery(self.path)
        self.recover(plan)
        self.assertTrue(self.engine.verify(self.run_id)["all_supported_repairs_verified"])

    def test_concurrent_retries_produce_one_forward_action(self):
        other = self.engine.create_run()
        with ThreadPoolExecutor(max_workers=4) as executor:
            ids = list(executor.map(
                lambda _: self.engine.forward(other, "discount", "sales"), range(8),
            ))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.engine.snapshot(other)["actions"]), 1)

    def test_concurrent_recovery_is_idempotent(self):
        plan = self.plan()
        self.approve(plan)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(
                lambda _: self.engine.execute(plan["id"], plan["digest"], "operations"),
                range(8),
            ))
        state = self.engine.snapshot(self.run_id)
        events = [e for e in state["events"] if e["type"] == "recovery"]
        self.assertEqual(len(events), 2)

    def test_new_plan_after_partial_recovery_does_not_repeat_repairs(self):
        plan = self.plan()
        self.approve(plan)
        self.engine.execute(plan["id"], plan["digest"], "operations")
        fresh = self.plan()
        self.assertEqual(
            sum(i["state"] == "completed" for i in fresh["body"]["items"]), 2,
        )
        self.approve(fresh)
        self.recover(fresh)
        self.assertTrue(self.engine.verify(self.run_id)["all_supported_repairs_verified"])

    def test_run_isolation(self):
        other = self.engine.create_run()
        plan = self.plan()
        self.approve(plan)
        self.recover(plan)
        self.assertEqual(self.engine.snapshot(other)["resources"]["crm"]["discount"], 3)
        self.assertEqual(self.engine.snapshot(other)["actions"], [])

    def test_export_contains_valid_serializable_state(self):
        state = self.engine.snapshot(self.run_id)
        self.assertEqual(json.loads(json.dumps(state))["id"], self.run_id)

    def test_no_actions_cannot_be_called_verified(self):
        empty = self.engine.create_run()
        self.assertFalse(self.engine.verify(empty)["all_supported_repairs_verified"])
        with self.assertRaises(ValueError):
            self.engine.prepare(empty)

    def test_verifier_detects_a_lost_human_edit(self):
        self.engine.human_edit(self.run_id, "contact", "Maya Chen")
        plan = self.plan()
        self.approve(plan)
        self.recover(plan)
        with self.engine.transaction() as db:
            self.engine.change(db, self.run_id, "crm", {"contact": "Accidental overwrite"})
        verification = self.engine.verify(self.run_id)
        self.assertFalse(verification["preserved_human_edits"][0]["passed"])
        self.assertFalse(verification["all_supported_repairs_verified"])


if __name__ == "__main__":
    unittest.main()
