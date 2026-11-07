"""Browser-test-only HTTP fixture; no live GitHub client is used."""

import argparse
from pathlib import Path

from countermand.server import Handler, Workbench
from countermand.store import now
from test_github import FakeGitHub


class FixtureHandler(Handler):
    def do_POST(self):
        if self.path != "/__fixture__/adopt":
            return super().do_POST()
        try:
            if not self._valid_host():
                raise PermissionError("Invalid fixture host")
            self._human(self._role())
            self._origin()
            body = self._body()
            issue = self.server.github.client.issues[body["number"]]
            issue["title"] = body["title"]
            issue["comments"] += 1
            issue["updated_at"] = now()
            self._send(200, {"fixture_only": True, "number": issue["number"]})
        except PermissionError as error:
            self._send(403, {"error": str(error)})
        except (KeyError, ValueError, TypeError):
            self._send(400, {"error": "Invalid fixture adoption request"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    server = Workbench(("127.0.0.1", args.port), args.state_dir, github_writes=True)
    server.github.client = FakeGitHub()
    server.RequestHandlerClass = FixtureHandler
    print("TEST FIXTURE: GitHub is in-memory only. No real GitHub requests or writes.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
