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
    print(f"Cursor Agent CLI: {shutil.which('agent') or 'not found on PATH'}")
    print(f"Codex (alternative): {shutil.which('codex') or 'not found on PATH'}")
    print(f"Local GitHub configuration: {(ROOT / '.countermand' / 'github.json').exists()}")
    print("MCP process descriptions (configure each agent separately; not both in a shared scope):")
    for role in ("sales", "operations"):
        role_file = ROOT / ".countermand" / f"mcp-{role}.json"
        args = [str(ROOT / "countermand" / "mcp.py"), "--role", role]
        if role_file.exists():
            args.extend(["--credential-file", str(role_file)])
        print(json.dumps({
            "role": "Sales / executor" if role == "sales" else "Operations / reviewer",
            "command": sys.executable,
            "args": args,
        }, indent=2))
        if not role_file.exists():
            print("Supply this role's COUNTERMAND_ADAPTER_TOKEN privately or configure its "
                  "role-only credential file. Never pass the human credential.")
    print("Start the web server first so it generates local credentials.")
    print("These are local process descriptions, not a claim that Switch or Codex is connected.")


if __name__ == "__main__":
    main()
