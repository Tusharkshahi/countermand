"""Read-only portability checks and credential-free MCP launch descriptions."""

import json
import platform
import shutil
import sys

from .server import ROOT


def main():
    print(f"Python: {platform.python_version()} / {platform.system()}")
    print(f"Project: {ROOT}")
    print(f"Git: {shutil.which('git') or 'not found'}")
    print(f"Codex: {shutil.which('codex') or 'not found on PATH; verify its provider setup'}")
    print(f"Local GitHub configuration: {(ROOT / '.countermand' / 'github.json').exists()}")
    print("MCP process descriptions (configure each agent separately; not both in a shared scope):")
    for role in ("sales", "operations"):
        print(json.dumps({
            "role": "GitHub executor" if role == "sales" else "GitHub reviewer",
            "command": sys.executable,
            "args": [str(ROOT / "countermand" / "mcp.py"), "--role", role,
                     "--credential-file", str(ROOT / ".countermand" / "credentials.json")],
        }, indent=2))
    print("Start the web server first so it generates credentials.json.")
    print("These are local process descriptions, not a claim that Switch or Codex is connected.")


if __name__ == "__main__":
    main()
