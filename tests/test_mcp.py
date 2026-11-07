import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from countermand.mcp import Adapter, dispatch


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.sales = Adapter("http://127.0.0.1:8787", "sales-test-token", "sales")
        self.operations = Adapter("http://127.0.0.1:8787", "ops-test-token", "operations")

    def test_tools_are_scoped_and_do_not_include_human_approval(self):
        sales = {tool["name"] for tool in self.sales.tools()}
        ops = {tool["name"] for tool in self.operations.tools()}
        self.assertIn("apply_demo_discount", sales)
        self.assertNotIn("create_demo_invoice", sales)
        self.assertIn("create_demo_invoice", ops)
        self.assertNotIn("apply_demo_discount", ops)
        self.assertFalse(any("approve" in name for name in sales | ops))

    def test_remote_urls_and_missing_credentials_are_rejected(self):
        for url in ("https://example.com", "http://example.com", "file:///tmp/state",
                    "http://localhost:8787?forward=somewhere"):
            with self.assertRaises(ValueError):
                Adapter(url, "token", "sales")
        for token in (None, "", " ", 12, True):
            with self.assertRaises(ValueError):
                Adapter("http://localhost:8787", token, "sales")

    def test_stdio_process_discovers_tools_with_windows_bom_credential_file(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials = Path(directory) / "role.json"
            credentials.write_text(json.dumps({"sales": "private-test-sales-key"}),
                                   encoding="utf-8-sig")
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ]
            env = dict(os.environ)
            env.pop("COUNTERMAND_ADAPTER_TOKEN", None)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "countermand" / "mcp.py"),
                 "--role", "sales", "--credential-file", str(credentials)],
                input="\n".join(json.dumps(m) for m in messages) + "\n",
                text=True, capture_output=True, env=env, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            responses = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([r["id"] for r in responses], [1, 2])
            names = {tool["name"] for tool in responses[1]["result"]["tools"]}
            self.assertIn("apply_demo_discount", names)
            self.assertNotIn("create_demo_invoice", names)
            self.assertNotIn("private-test-sales-key", result.stdout + result.stderr)

    def test_owner_cannot_select_another_owners_tool(self):
        with self.assertRaisesRegex(ValueError, "not available"):
            self.sales.call("create_demo_invoice", {"run_id": "run_123456abcdef"})

    def test_extra_arguments_and_path_injection_are_rejected(self):
        for arguments in ({"run_id": "run_123456abcdef", "owner": "human"},
                          {"run_id": "../../plans"}, {}, {"run_id": 12}):
            with self.assertRaises(ValueError):
                self.sales.call("inspect_workflow", arguments)

    def test_forward_does_not_send_a_user_selected_owner(self):
        with patch.object(self.sales, "request", return_value={"ok": True}) as request:
            self.sales.call("apply_demo_discount", {"run_id": "run_123456abcdef"})
        request.assert_called_once_with("/api/runs/run_123456abcdef/actions",
                                        {"kind": "discount"})

    def test_recovery_requires_exact_plan_and_digest(self):
        with patch.object(self.sales, "request", return_value={}) as request:
            self.sales.call("recover_owned_actions", {
                "plan_id": "plan_123456abcdef", "digest": "a" * 64,
            })
        request.assert_called_once_with("/api/plans/plan_123456abcdef/execute",
                                        {"digest": "a" * 64})

    def test_initialize_negotiates_protocol(self):
        result = dispatch(self.sales, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        })
        self.assertEqual(result["result"]["protocolVersion"], "2025-06-18")

    def test_notifications_do_not_emit_responses(self):
        self.assertIsNone(dispatch(self.sales, {
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }))

    def test_invalid_calls_are_tool_errors_not_successes(self):
        result = dispatch(self.sales, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "approve", "arguments": {}},
        })
        self.assertTrue(result["result"]["isError"])
        self.assertNotIn("sales-test-token", str(result))


if __name__ == "__main__":
    unittest.main()
