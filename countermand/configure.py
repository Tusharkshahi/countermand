"""Configure the sandbox credential locally, without printing it or sending writes."""

import getpass
import json
from pathlib import Path

from .github_client import DEFAULT_REPO, GitHubClient
from .server import ROOT


def main():
    print("GitHub sandbox setup. No issues or code will be modified by this command.")
    print("Use a fine-grained token restricted to the sandbox repository:")
    print("Repository permissions: Issues read/write; Metadata read. No Contents permission.")
    repo = input(f"Repository [{DEFAULT_REPO}]: ").strip() or DEFAULT_REPO
    token = getpass.getpass("GitHub token (hidden; do not paste it into chat): ").strip()
    if not token:
        raise SystemExit("No token entered. Nothing saved.")
    try:
        metadata = GitHubClient(token, repo).inspect_repo()
    except ValueError as error:
        raise SystemExit(f"Read-only validation failed: {error}") from None
    directory = ROOT / ".countermand"
    directory.mkdir(exist_ok=True)
    directory.chmod(0o700)
    target = directory / "github.json"
    if target.exists() and input("Replace the existing local GitHub configuration? [y/N]: ").lower() != "y":
        raise SystemExit("Existing configuration preserved.")
    with target.open("w", encoding="utf-8") as handle:
        target.chmod(0o600)
        json.dump({"repo": repo, "token": token}, handle)
    print(f"Configured {metadata['full_name']}. No GitHub writes were performed.")
    print("Keep .countermand private. chmod is not a Windows ACL security boundary.")
    print("Next: start-windows.cmd --github-writes, then open http://127.0.0.1:8787/github")


if __name__ == "__main__":
    main()
