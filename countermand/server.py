"""Loopback-only web workbench and role-scoped synthetic adapter API."""

import argparse
import hmac
import json
import mimetypes
import os
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .recovery import Recovery, StalePlan
from .github_client import DEFAULT_REPO, GitHubClient
from .github_recovery import GitHubRecovery
from .github_routes import get_github, post_github


ROOT = Path(__file__).resolve().parent.parent


class Workbench(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, state_dir, browser_origins=(), github_writes=False):
        self.browser_origins = frozenset(browser_origins)
        for origin in self.browser_origins:
            parsed = urlsplit(origin)
            if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1")
                    or parsed.path or parsed.query or parsed.fragment or parsed.username):
                raise ValueError("Additional browser origins must be explicit loopback HTTP origins")
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_dir.chmod(0o700)
        self.engine = Recovery(state_dir / "state.sqlite3")
        github_path = state_dir / "github.json"
        github_config = json.loads(github_path.read_text()) if github_path.exists() else {}
        self.github = GitHubRecovery(
            state_dir / "state.sqlite3",
            GitHubClient(
                os.environ.get("COUNTERMAND_GITHUB_TOKEN", github_config.get("token", "")),
                os.environ.get("COUNTERMAND_GITHUB_REPO", github_config.get("repo", DEFAULT_REPO)),
            ),
            writes_enabled=github_writes,
        )
        key_path = state_dir / "credentials.json"
        if key_path.exists():
            self.keys = json.loads(key_path.read_text())
        else:
            self.keys = {role: secrets.token_urlsafe(32)
                         for role in ("sales", "operations", "human")}
            with key_path.open("x", encoding="utf-8") as handle:
                key_path.chmod(0o600)
                json.dump(self.keys, handle)
        self.browser_session = secrets.token_urlsafe(32)
        if not self.engine.list_runs():
            self.engine.create_run()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "Countermand/0.1"

    def _valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"localhost:{port}", f"127.0.0.1:{port}")

    def _role(self):
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[7:]
            for role, key in self.server.keys.items():
                if hmac.compare_digest(token.encode(), key.encode()):
                    return role
            raise PermissionError("Invalid adapter credential")
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        value = cookie.get("countermand_session")
        if value and hmac.compare_digest(value.value.encode(), self.server.browser_session.encode()):
            return "human"
        raise PermissionError("Open the workbench locally or provide an adapter credential")

    def _send(self, status, body, content_type="application/json", session=False):
        payload = json.dumps(body).encode() if content_type == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if session:
            self.send_header("Set-Cookie", "countermand_session="
                             f"{self.server.browser_session}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(payload)

    def _body(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("Mutations require application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 16_384:
            raise ValueError("Request body must contain 1 to 16384 bytes")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        return body

    def _origin(self):
        origin = self.headers.get("Origin")
        expected = f"http://{self.headers['Host']}"
        allowed = {expected, *self.server.browser_origins}
        if origin and origin not in allowed:
            raise PermissionError("Cross-origin requests are not allowed")
        if not self.headers.get("Authorization") and origin not in allowed:
            raise PermissionError("Browser mutations require the workbench origin")

    @staticmethod
    def _human(role):
        if role != "human":
            raise PermissionError("This operation requires a human credential")

    def do_GET(self):
        try:
            if not self._valid_host():
                raise PermissionError("This workbench only serves its loopback host")
            path = urlsplit(self.path).path
            if path == "/health":
                return self._send(200, {"status": "ok", "switch_connected": False})
            files = {"/": "index.html", "/app.js": "app.js", "/view.js": "view.js",
                     "/styles.css": "styles.css",
                     "/favicon.svg": "favicon.svg", "/github": "github.html",
                     "/github.js": "github.js"}
            if path in files:
                file = ROOT / "web" / files[path]
                mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                return self._send(200, file.read_bytes(), mime, session=path in ("/", "/github"))
            role = self._role()
            github_result = get_github(self.server, path.strip("/").split("/"))
            if github_result is not None:
                return self._send(*github_result)
            if path == "/api/runs":
                return self._send(200, {"runs": self.server.engine.list_runs(),
                                        "switch_connected": False, "role": role})
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                return self._send(200, self.server.engine.snapshot(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "evidence":
                return self._send(200, {
                    "workflow": self.server.engine.snapshot(parts[2]),
                    "verification": self.server.engine.verify(parts[2]),
                })
            return self._send(404, {"error": "Not found"})
        except PermissionError as error:
            self._send(403, {"error": str(error)})
        except (ValueError, KeyError) as error:
            self._send(400, {"error": str(error)})

    def do_POST(self):
        try:
            if not self._valid_host():
                raise PermissionError("Invalid workbench host")
            role = self._role()
            self._origin()
            body = self._body()
            parts = urlsplit(self.path).path.strip("/").split("/")
            github_result = post_github(self.server, parts, body, role)
            if github_result is not None:
                return self._send(*github_result)
            engine = self.server.engine
            if parts == ["api", "runs"]:
                self._human(role)
                run_id = engine.create_run(body.get("mode", "rehearsal"))
                return self._send(201, engine.snapshot(run_id))
            if len(parts) == 4 and parts[:2] == ["api", "runs"]:
                run_id, operation = parts[2:]
                snapshot = engine.snapshot(run_id)
                if operation == "actions":
                    owner = role
                    if role == "human":
                        if snapshot["mode"] != "rehearsal":
                            raise PermissionError("Only real owning adapters may act in external mode")
                        owner = body.get("owner")
                    engine.forward(run_id, body["kind"], owner)
                elif operation == "human-edit":
                    self._human(role)
                    engine.human_edit(run_id, body["field"], body["value"])
                elif operation == "plans":
                    return self._send(201, engine.prepare(run_id))
                else:
                    return self._send(404, {"error": "Unknown workflow operation"})
                return self._send(200, engine.snapshot(run_id))
            if len(parts) == 4 and parts[:2] == ["api", "plans"]:
                plan_id, operation = parts[2:]
                digest = body["digest"]
                if operation == "approve":
                    self._human(role)
                    run_id = engine.approve(plan_id, digest, "local-demo-human")
                    return self._send(200, engine.snapshot(run_id))
                if operation == "execute":
                    owner = role
                    if role == "human":
                        with engine.transaction() as db:
                            _, plan_body = engine._load_plan(db, plan_id, digest)
                            run = db.execute("SELECT mode FROM runs WHERE id=?",
                                             (plan_body["run_id"],)).fetchone()
                        if run["mode"] != "rehearsal":
                            raise PermissionError("Human rehearsal execution is disabled for this run")
                        owner = body.get("owner")
                    return self._send(200, engine.execute(plan_id, digest, owner))
            return self._send(404, {"error": "Not found"})
        except PermissionError as error:
            self._send(403, {"error": str(error)})
        except StalePlan as error:
            self._send(409, {"error": str(error), "code": "stale_plan"})
        except (ValueError, KeyError, TypeError) as error:
            self._send(400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description="Countermand local recovery workbench")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".countermand")
    parser.add_argument("--browser-origin", action="append", default=[],
                        help="Explicit additional loopback origin for a local preview proxy")
    parser.add_argument("--github-writes", action="store_true",
                        help="Opt in to the separately confirmed, bounded GitHub issue pilot")
    args = parser.parse_args()
    server = Workbench(("127.0.0.1", args.port), args.state_dir, args.browser_origin,
                       args.github_writes)
    print(f"Countermand: http://127.0.0.1:{args.port}", flush=True)
    print("Switch is not connected. The CRM/mail rehearsal is synthetic; no real mail or payments.", flush=True)
    print("GitHub issue writes: " + ("ENABLED; exact repository confirmation still required."
                                    if args.github_writes else "disabled (default)."), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
