"""Dependency-free, scoped stdio MCP tools for Switch-managed coding agents."""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


RUN = {"type": "string", "pattern": "^run_[a-f0-9]{12}$"}
PLAN = {"type": "string", "pattern": "^plan_[a-f0-9]{12}$"}
DIGEST = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
GH_RUN = {"type": "string", "pattern": "^ghrun_[a-f0-9]{12}$"}
GH_PLAN = {"type": "string", "pattern": "^ghplan_[a-f0-9]{12}$"}


class Adapter:
    def __init__(self, base_url, token, role):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1")
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or parsed.username):
            raise ValueError("The adapter only connects to a loopback HTTP workbench")
        if role not in ("sales", "operations"):
            raise ValueError("An adapter must be sales or operations")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Set COUNTERMAND_ADAPTER_TOKEN to this adapter's credential")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.role = role

    def tools(self):
        definitions = [
            ("inspect_workflow", "Read the shared synthetic workflow ledger.", {"run_id": RUN}),
            ("prepare_recovery", "Preview an exact recovery plan and freeze new forward work "
             "for this run. Does not approve or execute repairs.",
             {"run_id": RUN}),
            ("recover_owned_actions", "Execute only this owner's actions in a human-approved "
             "plan. Stale state is refused.", {"plan_id": PLAN, "digest": DIGEST}),
            ("verify_recovery", "Read fresh service state and residual consequences.",
             {"run_id": RUN}),
        ]
        if self.role == "sales":
            definitions.append((
                "apply_demo_discount",
                "Apply the deliberately incorrect 30% discount to a synthetic customer. "
                "For the bounded demo only; this is not a general CRM tool.",
                {"run_id": RUN},
            ))
        else:
            definitions.extend([
                ("create_demo_invoice", "Create a synthetic draft from the recorded discount.",
                 {"run_id": RUN}),
                ("deliver_demo_notice", "Deliver a notice to the local test mailbox only. "
                 "No real email is sent.", {"run_id": RUN}),
            ])
        definitions.extend([
            ("inspect_github_run", "Read receipts for an explicitly authorized GitHub pilot.",
             {"run_id": GH_RUN}),
            ("verify_github_recovery", "Read actual GitHub state and recovery limitations.",
             {"run_id": GH_RUN}),
        ])
        if self.role == "sales":
            definitions.extend([
                ("create_github_issue", "REAL WRITE: create a task from the immutable "
                 "human-authorized manifest (one to three marked issues per run). "
                 "Inspect tasks first; never invent an extra slot or retry an uncertain creation.",
                 {"run_id": GH_RUN, "slot": {"type": "integer", "minimum": 0, "maximum": 2}}),
                ("recover_github_issues", "REAL WRITE: close only unchanged tracked issues in "
                 "an exact human-approved plan. Changed issues are preserved. Not atomic.",
                 {"plan_id": GH_PLAN, "digest": DIGEST}),
            ])
        else:
            definitions.append((
                "prepare_github_recovery", "Read real GitHub state and classify changed issues "
                "for preservation. Preview only; cannot approve or close anything.",
                {"run_id": GH_RUN},
            ))
        return [{"name": name, "description": description, "inputSchema": {
            "type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False,
        }} for name, description, properties in definitions]

    def request(self, path, body=None):
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                detail = json.load(error).get("error", f"HTTP {error.code}")
            except (ValueError, AttributeError):
                detail = f"HTTP {error.code}"
            finally:
                error.close()
            raise ValueError(detail) from None
        except urllib.error.URLError:
            raise ValueError("The local workbench is unavailable. Start it first.") from None

    def call(self, name, arguments):
        definition = next((tool for tool in self.tools() if tool["name"] == name), None)
        if not definition:
            raise ValueError("Unknown tool or tool not available to this owner")
        properties = definition["inputSchema"]["properties"]
        if not isinstance(arguments, dict) or set(arguments) != set(properties):
            raise ValueError("Tool arguments must match the declared schema exactly")
        for field, schema in properties.items():
            value = arguments[field]
            if schema["type"] == "integer":
                valid = type(value) is int and schema["minimum"] <= value <= schema["maximum"]
            else:
                valid = isinstance(value, str) and re.fullmatch(schema["pattern"], value)
            if not valid:
                raise ValueError(f"Invalid {field}")
        run_id = arguments.get("run_id")
        if name == "inspect_github_run":
            return self.request(f"/api/github/runs/{run_id}/inspect")
        if name == "verify_github_recovery":
            return self.request(f"/api/github/runs/{run_id}/evidence")
        if name == "prepare_github_recovery":
            return self.request(f"/api/github/runs/{run_id}/plan", {})
        if name == "create_github_issue":
            return self.request(f"/api/github/runs/{run_id}/issues", {"slot": arguments["slot"]})
        if name == "recover_github_issues":
            return self.request(f"/api/github/plans/{arguments['plan_id']}/execute",
                                {"digest": arguments["digest"]})
        if name == "inspect_workflow":
            return self.request(f"/api/runs/{run_id}")
        if name == "verify_recovery":
            return self.request(f"/api/runs/{run_id}/evidence")
        if name == "prepare_recovery":
            return self.request(f"/api/runs/{run_id}/plans", {})
        if name == "recover_owned_actions":
            return self.request(f"/api/plans/{arguments['plan_id']}/execute",
                                {"digest": arguments["digest"]})
        kind = {"apply_demo_discount": "discount", "create_demo_invoice": "invoice",
                "deliver_demo_notice": "message"}[name]
        return self.request(f"/api/runs/{run_id}/actions", {"kind": kind})


def dispatch(adapter, message):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Invalid JSON-RPC request"}}
    if "id" not in message:
        return None
    response = {"jsonrpc": "2.0", "id": message["id"]}
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return {**response, "error": {"code": -32602, "message": "Params must be an object"}}
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in (
            "2024-11-05", "2025-03-26", "2025-06-18",
        ) else "2024-11-05"
        result = {
            "protocolVersion": version, "capabilities": {"tools": {}},
            "serverInfo": {"name": f"countermand-{adapter.role}", "version": "0.1.0"},
            "instructions": "Local rehearsal plus opt-in real GitHub Issues tools. "
                            "GitHub writes require explicit human run authorization and separate "
                            "plan approval. Never claim a real email was sent "
                            "or Switch is connected solely because these tools are available. "
                            "There is deliberately no human-approval tool.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": adapter.tools()}
    elif method == "tools/call":
        try:
            output = adapter.call(params.get("name"), params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": json.dumps(output)}]}
        except (ValueError, TypeError) as error:
            result = {"isError": True, "content": [{"type": "text", "text": str(error)}]}
    else:
        return {**response, "error": {"code": -32601, "message": "Method not found"}}
    return {**response, "result": result}


def main():
    parser = argparse.ArgumentParser(description="Countermand scoped stdio MCP adapter")
    parser.add_argument("--role", required=True, choices=("sales", "operations"))
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--credential-file",
                        help="Local generated credentials.json; select only this adapter's role")
    args = parser.parse_args()
    try:
        token = os.environ.get("COUNTERMAND_ADAPTER_TOKEN")
        if not token and args.credential_file:
            with open(args.credential_file, encoding="utf-8-sig") as handle:
                credentials = json.load(handle)
            if not isinstance(credentials, dict):
                raise ValueError("The credential file must contain a role-to-token JSON object")
            token = credentials.get(args.role)
        adapter = Adapter(args.url, token, args.role)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    for line in sys.stdin:
        if len(line) > 1_048_576:
            print("MCP input exceeds the local adapter's size limit", file=sys.stderr)
            continue
        try:
            response = dispatch(adapter, json.loads(line))
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
