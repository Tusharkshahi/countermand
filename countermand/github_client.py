"""Narrow GitHub Issues client. No code, repository, label, or deletion operations."""

import hashlib
import json
import re
import urllib.error
import urllib.request

from .store import encode


DEFAULT_REPO = "Tusharkshahi/TaskMind"


def fingerprint(issue):
    fields = ("id", "number", "title", "body", "state", "state_reason", "updated_at",
              "comments", "locked", "assignees", "labels", "milestone")
    selected = {key: issue.get(key) for key in fields}
    return hashlib.sha256(encode(selected).encode()).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class GitHubClient:
    def __init__(self, token="", repo=DEFAULT_REPO):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Repository must be owner/name")
        self.repo = repo
        self.token = token
        self.configured = bool(token)

    def request(self, method, suffix="", body=None, etag=None):
        if not self.token:
            raise ValueError("Configure a repository-scoped GitHub token on this machine first")
        headers = {
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Countermand-Hackathon",
            "Cache-Control": "no-cache",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if etag:
            headers["If-Match"] = etag
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{suffix}", method=method,
            headers=headers, data=encode(body).encode() if body is not None else None,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=15) as response:
                return json.load(response), response.headers.get("ETag")
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise ValueError(f"GitHub returned HTTP {status}. Inspect the repository; "
                             "writes are never automatically retried.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ValueError("GitHub was unreachable. A write may have committed; "
                             "do not retry it blindly.") from None

    def inspect_repo(self):
        data, _ = self.request("GET")
        if data.get("full_name", "").lower() != self.repo.lower():
            raise ValueError("The response does not match the configured repository")
        if data.get("archived") or not data.get("has_issues"):
            raise ValueError("The configured repository must be active with Issues enabled")
        return {"full_name": data["full_name"], "html_url": data["html_url"],
                "has_issues": data["has_issues"]}

    def create_issue(self, title, body):
        return self.request("POST", "/issues", {"title": title, "body": body})[0]

    def get_issue(self, number):
        if type(number) is not int or number < 1:
            raise ValueError("Invalid tracked issue number")
        return self.request("GET", f"/issues/{number}")

    def close_issue(self, number, etag):
        if type(number) is not int or number < 1:
            raise ValueError("Invalid tracked issue number")
        return self.request("PATCH", f"/issues/{number}",
                            {"state": "closed", "state_reason": "not_planned"}, etag)[0]
