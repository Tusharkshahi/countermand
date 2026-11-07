import copy
import tempfile
import unittest
from pathlib import Path

from countermand.github_recovery import GitHubRecovery
from countermand.package import source_files
from countermand.recovery import StalePlan


class FakeGitHub:
    repo = "Tusharkshahi/TaskMind"
    configured = True

    def __init__(self):
        self.issues = {}
        self.closes = []
        self.fail_create = False
        self.fail_close = False

    def inspect_repo(self):
        return {"full_name": self.repo, "html_url": f"https://github.com/{self.repo}",
                "has_issues": True}

    def create_issue(self, title, body):
        number = len(self.issues) + 10
        issue = {"id": number + 100, "number": number, "title": title, "body": body,
                 "state": "open", "state_reason": None, "comments": 0, "locked": False,
                 "labels": [], "assignees": [], "milestone": None, "updated_at": "initial",
                 "html_url": f"https://github.com/{self.repo}/issues/{number}"}
        self.issues[number] = issue
        if self.fail_create:
            raise ValueError("Response lost after write")
        return copy.deepcopy(issue)

    def get_issue(self, number):
        return copy.deepcopy(self.issues[number]), '"test-etag"'

    def close_issue(self, number, etag):
        self.closes.append(number)
        self.issues[number].update(state="closed", state_reason="not_planned",
                                   updated_at="closed")
        if self.fail_close:
            raise ValueError("Close response lost")
        return copy.deepcopy(self.issues[number])


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = FakeGitHub()
        self.engine = GitHubRecovery(Path(self.directory.name) / "state.sqlite3",
                                     self.client, writes_enabled=True)
        self.run_id = self.engine.authorize(self.client.repo, "human")["id"]

    def tearDown(self):
        self.directory.cleanup()

    def create(self):
        for slot in range(3):
            self.engine.create_issue(self.run_id, slot, "sales")

    def plan(self):
        return self.engine.prepare(self.run_id)["plan"]

    def approve(self, plan):
        self.engine.approve(plan["id"], plan["digest"], "human", True)

    def test_writes_are_opt_in_and_exact_repository_authorized(self):
        self.engine.writes_enabled = False
        with self.assertRaises(PermissionError):
            self.engine.authorize(self.client.repo, "human")
        with self.assertRaises(PermissionError):
            self.engine.create_issue(self.run_id, 0, "sales")
        self.engine.writes_enabled = True
        with self.assertRaises(ValueError):
            self.engine.authorize("someone/other", "human")
        self.assertEqual(len(self.client.issues), 0)

    def test_only_three_slots_can_be_created_and_retries_are_idempotent(self):
        self.create()
        self.engine.create_issue(self.run_id, 0, "sales")
        self.assertEqual(len(self.client.issues), 3)
        with self.assertRaises(ValueError):
            self.engine.create_issue(self.run_id, 3, "sales")
        with self.assertRaises(PermissionError):
            self.engine.create_issue(self.run_id, 0, "operations")

    def test_changed_issue_is_preserved_and_untouched_issues_closed(self):
        self.create()
        self.client.issues[11].update(title="A human has adopted this task",
                                      comments=1, updated_at="human-edit")
        plan = self.plan()
        self.assertEqual([i["classification"] for i in plan["body"]["items"]],
                         ["close", "preserve", "close"])
        self.approve(plan)
        self.engine.execute(plan["id"], plan["digest"], "sales")
        self.assertEqual(self.client.closes, [10, 12])
        self.assertEqual(self.client.issues[11]["state"], "open")
        self.assertEqual(self.client.issues[11]["title"], "A human has adopted this task")
        evidence = self.engine.evidence(self.run_id)
        self.assertTrue(all(c["passed"] for c in evidence["verification"]["checks"]))
        self.assertFalse(evidence["verification"]["atomic_recovery_guaranteed"])
        self.assertFalse(evidence["verification"]["fully_reversed"])

    def test_approval_and_limitation_acknowledgment_required(self):
        self.create()
        plan = self.plan()
        with self.assertRaises(ValueError):
            self.engine.execute(plan["id"], plan["digest"], "sales")
        with self.assertRaises(ValueError):
            self.engine.approve(plan["id"], plan["digest"], "human")
        with self.assertRaises(PermissionError):
            self.engine.approve(plan["id"], plan["digest"], "operations", True)
        with self.assertRaises(ValueError):
            self.engine.approve(plan["id"], "wrong", "human", True)
        self.assertEqual(self.client.closes, [])

    def test_new_change_after_preview_invalidates_approval(self):
        self.create()
        plan = self.plan()
        self.client.issues[10]["comments"] = 1
        with self.assertRaises(StalePlan):
            self.approve(plan)
        self.assertEqual(self.client.closes, [])

    def test_new_change_after_approval_stops_all_closures(self):
        self.create()
        plan = self.plan()
        self.approve(plan)
        self.client.issues[12]["title"] = "New human work"
        with self.assertRaises(StalePlan):
            self.engine.execute(plan["id"], plan["digest"], "sales")
        self.assertEqual(self.client.closes, [])

    def test_repeated_recovery_does_not_repeat_closures_or_receipts(self):
        self.create()
        plan = self.plan()
        self.approve(plan)
        self.engine.execute(plan["id"], plan["digest"], "sales")
        events = self.engine.snapshot(self.run_id)["events"]
        self.engine.execute(plan["id"], plan["digest"], "sales")
        self.assertEqual(self.client.closes, [10, 11, 12])
        self.assertEqual(events, self.engine.snapshot(self.run_id)["events"])

    def test_uncertain_creation_is_not_retried(self):
        self.client.fail_create = True
        with self.assertRaises(ValueError):
            self.engine.create_issue(self.run_id, 0, "sales")
        self.client.fail_create = False
        with self.assertRaisesRegex(ValueError, "uncertain"):
            self.engine.create_issue(self.run_id, 0, "sales")
        self.assertEqual(len(self.client.issues), 1)
        self.assertEqual(self.engine.snapshot(self.run_id)["actions"][0]["status"], "unknown")

    def test_uncertain_close_blocks_retry_and_other_closures(self):
        self.create()
        plan = self.plan()
        self.approve(plan)
        self.client.fail_close = True
        with self.assertRaises(ValueError):
            self.engine.execute(plan["id"], plan["digest"], "sales")
        with self.assertRaises(ValueError):
            self.engine.execute(plan["id"], plan["digest"], "sales")
        self.assertEqual(self.client.closes, [10])
        self.assertEqual(self.engine.snapshot(self.run_id)["plan"]["status"], "uncertain")

    def test_preexisting_issue_is_never_considered(self):
        self.client.issues[999] = {"id": 999, "number": 999, "state": "open"}
        self.create()
        plan = self.plan()
        self.approve(plan)
        self.engine.execute(plan["id"], plan["digest"], "sales")
        self.assertEqual(self.client.issues[999]["state"], "open")
        self.assertNotIn(999, self.client.closes)

    def test_reviewer_cannot_execute(self):
        self.create()
        plan = self.plan()
        self.approve(plan)
        with self.assertRaises(PermissionError):
            self.engine.execute(plan["id"], plan["digest"], "operations")

    def test_archive_allowlist_excludes_credentials_and_local_state(self):
        names = [str(relative) for _, relative in source_files()]
        self.assertIn("start-windows.cmd", names)
        self.assertIn("WINDOWS.md", names)
        self.assertFalse(any(".countermand" in name or "__pycache__" in name for name in names))
        self.assertFalse(any(name.endswith(".json") or name.endswith(".sqlite3") for name in names))


if __name__ == "__main__":
    unittest.main()
