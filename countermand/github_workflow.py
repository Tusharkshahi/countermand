"""Bounded live pilot: at most three new, explicitly authorized issues per run."""

import json
import threading

from .github_client import fingerprint
from .store import Store, encode, identifier, now


ISSUES = (
    ("Define kickoff acceptance criteria", "Draft the acceptance checklist for the demo kickoff."),
    ("Prepare the implementation checklist", "List implementation steps for the demo kickoff."),
    ("Review the rollout plan", "Review the rollout and communication steps for the demo kickoff."),
)


def validate_tasks(tasks):
    if tasks is None:
        tasks = [{"title": title, "body": body} for title, body in ISSUES]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 3:
        raise ValueError("Authorize between one and three task definitions")
    result = []
    for task in tasks:
        if (not isinstance(task, dict) or "title" not in task
                or set(task) - {"title", "body"}):
            raise ValueError("Each task accepts only a title and optional body")
        title, body = task["title"], task.get("body", "")
        if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 120
                or "\n" in title or "\r" in title):
            raise ValueError("Task titles must be single-line text of 1 to 120 characters")
        if not isinstance(body, str) or len(body) > 4000:
            raise ValueError("Task bodies must contain at most 4000 characters")
        result.append({"title": title.strip(), "body": body.strip()})
    return result


class GitHubWorkflow(Store):
    def __init__(self, path, client, writes_enabled=False):
        super().__init__(path)
        self.client = client
        self.writes_enabled = writes_enabled
        self.lock = threading.RLock()
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS gh_runs (
                    id TEXT PRIMARY KEY, repo TEXT NOT NULL, created_at TEXT NOT NULL,
                    authorized_by TEXT NOT NULL, authorization TEXT NOT NULL,
                    intent TEXT NOT NULL DEFAULT 'Project kickoff'
                );
                CREATE TABLE IF NOT EXISTS gh_tasks (
                    run_id TEXT NOT NULL REFERENCES gh_runs(id), slot INTEGER NOT NULL,
                    title TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (run_id, slot)
                );
                CREATE TABLE IF NOT EXISTS gh_actions (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES gh_runs(id),
                    slot INTEGER NOT NULL, status TEXT NOT NULL,
                    number INTEGER, url TEXT, baseline TEXT, observed TEXT,
                    recovery TEXT NOT NULL DEFAULT 'pending', UNIQUE(run_id,slot)
                );
                CREATE TABLE IF NOT EXISTS gh_plans (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES gh_runs(id),
                    digest TEXT NOT NULL, body TEXT NOT NULL,
                    status TEXT NOT NULL, approved_by TEXT, approved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS gh_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES gh_runs(id), actor TEXT NOT NULL,
                    title TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(gh_runs)")}
            if "intent" not in columns:
                db.execute("ALTER TABLE gh_runs ADD COLUMN intent TEXT NOT NULL "
                           "DEFAULT 'Project kickoff'")

    def status(self):
        return {
            "repo": self.client.repo, "configured": self.client.configured,
            "writes_enabled": self.writes_enabled, "switch_connected": None,
            "switch_status": "not_monitored",
            "supports_task_manifest": True,
            "scope": "At most three new issues per explicitly authorized run. No code changes.",
            "limitation": "GitHub recovery rechecks state before each close, but is not "
                          "a verified atomic compare-and-close. Pause collaborators during execution.",
        }

    def require_writes(self):
        if not self.writes_enabled or not self.client.configured:
            raise PermissionError("Live writes are disabled. Configure GitHub and explicitly "
                                  "start the server with --github-writes.")

    def authorize(self, confirmation, actor, tasks=None, intent="Project kickoff"):
        self.require_writes()
        if actor != "human":
            raise PermissionError("Only a human may authorize the immutable task manifest")
        if confirmation != self.client.repo:
            raise ValueError("Type the exact configured owner/repository to authorize new issues")
        tasks = validate_tasks(tasks)
        if (not isinstance(intent, str) or not 1 <= len(intent.strip()) <= 200
                or "\n" in intent or "\r" in intent):
            raise ValueError("Workflow intent must be single-line text of 1 to 200 characters")
        self.client.inspect_repo()
        run_id = identifier("ghrun")
        with self.transaction() as db:
            db.execute("INSERT INTO gh_runs(id,repo,created_at,authorized_by,authorization,intent) "
                       "VALUES (?,?,?,?,?,?)", (
                run_id, self.client.repo, now(), actor,
                f"Create exactly {len(tasks)} issues from the immutable task manifest. "
                "Existing issues and code are out of scope.", intent.strip(),
            ))
            for slot, task in enumerate(tasks):
                db.execute("INSERT INTO gh_tasks VALUES (?,?,?,?)",
                           (run_id, slot, task["title"], task["body"]))
            self.log(db, run_id, actor, "Live pilot authorized",
                     f"{len(tasks)} approved tasks in {self.client.repo}; no code changes.")
        return self.snapshot(run_id)

    @staticmethod
    def log(db, run_id, actor, title, detail):
        db.execute(
            "INSERT INTO gh_events(run_id,actor,title,detail,created_at) VALUES (?,?,?,?,?)",
            (run_id, actor, title, detail, now()),
        )

    def run(self, db, run_id):
        row = db.execute("SELECT * FROM gh_runs WHERE id=?", (run_id,)).fetchone()
        if not row or row["repo"] != self.client.repo:
            raise ValueError("Run not found for the configured repository")
        return dict(row)

    @staticmethod
    def tasks(db, run_id):
        rows = db.execute("SELECT title,body FROM gh_tasks WHERE run_id=? ORDER BY slot",
                          (run_id,)).fetchall()
        return [dict(row) for row in rows] if rows else validate_tasks(None)

    def create_issue(self, run_id, slot, actor):
        self.require_writes()
        if actor not in ("sales", "human"):
            raise PermissionError("Only the GitHub-owning executor may create issues")
        if type(slot) is not int or not 0 <= slot < len(ISSUES):
            raise ValueError("Choose a slot from 0 to 2")
        with self.lock:
            with self.transaction() as db:
                run = self.run(db, run_id)
                tasks = self.tasks(db, run_id)
                if slot >= len(tasks):
                    raise ValueError("This slot is not in the human-authorized task manifest")
                prior = db.execute("SELECT * FROM gh_actions WHERE run_id=? AND slot=?",
                                   (run_id, slot)).fetchone()
                if prior and prior["status"] == "recorded":
                    return self.snapshot_unlocked(db, run_id)
                if prior:
                    raise ValueError("This write has an uncertain outcome. Automatic retry is "
                                     "disabled; inspect GitHub for the run marker.")
                action_id = identifier("ghact")
                db.execute("INSERT INTO gh_actions(id,run_id,slot,status) VALUES (?,?,?,'pending')",
                           (action_id, run_id, slot))
            title, text = tasks[slot]["title"], tasks[slot]["body"]
            marker = f"<!-- countermand:{run_id}:{slot} -->"
            body = (f"{text}\n\n---\nWorkflow: {run['intent']}\n"
                    f"Tracked by Countermand under an explicit human authorization.\n\n{marker}")
            try:
                issue = self.client.create_issue(title, body)
                if (type(issue.get("number")) is not int or issue["number"] < 1
                        or type(issue.get("id")) is not int or issue["id"] < 1
                        or issue.get("title") != title or not issue.get("html_url")
                        or marker not in (issue.get("body") or "")
                        or issue.get("state") != "open"):
                    raise ValueError("GitHub did not return an intact issue receipt")
            except (ValueError, OSError, TimeoutError):
                with self.transaction() as db:
                    db.execute("UPDATE gh_actions SET status='unknown' WHERE id=?", (action_id,))
                    self.log(db, run_id, actor, "Issue creation outcome uncertain",
                             f"Slot {slot + 1}. Inspect GitHub for marker {marker}; do not retry.")
                raise
            with self.transaction() as db:
                db.execute(
                    "UPDATE gh_actions SET status='recorded',number=?,url=?,baseline=?,observed=? "
                    "WHERE id=?",
                    (issue["number"], issue["html_url"], encode(issue), encode(issue), action_id),
                )
                self.log(db, run_id, actor, f"Created issue #{issue['number']}",
                         f"Receipt recorded for slot {slot + 1}; only this issue may be recovered.")
            return self.snapshot(run_id)

    def snapshot_unlocked(self, db, run_id):
        result = self.run(db, run_id)
        result["tasks"] = self.tasks(db, run_id)
        result["actions"] = [
            {**dict(row), "baseline": json.loads(row["baseline"]) if row["baseline"] else None,
             "observed": json.loads(row["observed"]) if row["observed"] else None}
            for row in db.execute(
                "SELECT * FROM gh_actions WHERE run_id=? ORDER BY slot", (run_id,),
            )
        ]
        result["events"] = [dict(row) for row in db.execute(
            "SELECT * FROM gh_events WHERE run_id=? ORDER BY seq", (run_id,),
        )]
        row = db.execute("SELECT * FROM gh_plans WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
                         (run_id,)).fetchone()
        result["plan"] = {**dict(row), "body": json.loads(row["body"])} if row else None
        result["settings"] = self.status()
        return result

    def snapshot(self, run_id):
        with self.transaction() as db:
            return self.snapshot_unlocked(db, run_id)

    def list_runs(self):
        with self.transaction() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,repo,created_at,intent FROM gh_runs WHERE repo=? ORDER BY rowid DESC",
                (self.client.repo,),
            )]

    def inspect(self, run_id):
        with self.lock:
            state = self.snapshot(run_id)
            for action in state["actions"]:
                if action["status"] != "recorded":
                    continue
                current, _ = self.client.get_issue(action["number"])
                if current.get("id") != action["baseline"]["id"]:
                    raise ValueError("Issue identity no longer matches its receipt")
                with self.transaction() as db:
                    db.execute("UPDATE gh_actions SET observed=? WHERE id=?",
                               (encode(current), action["id"]))
            return self.snapshot(run_id)

    @staticmethod
    def classify(action, current):
        if action["recovery"] == "closed":
            return "completed" if current.get("state") == "closed" else "changed"
        if current.get("id") != action["baseline"]["id"]:
            return "blocked"
        if current.get("state") == "closed":
            return "already_closed"
        return "close" if fingerprint(current) == fingerprint(action["baseline"]) else "preserve"
