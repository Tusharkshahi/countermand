import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from countermand.server import Handler, Workbench
from countermand.mcp import Adapter


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.logging = patch.object(Handler, "log_message", lambda *args: None)
        cls.logging.start()
        cls.server = Workbench(("127.0.0.1", 0), cls.directory.name)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.logging.stop()
        cls.directory.cleanup()

    def request(self, method, path, body=None, role="human", extra=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Authorization": f"Bearer {self.server.keys[role]}"} if role else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra or {})
        connection.request(method, path, json.dumps(body) if body is not None else None,
                           headers)
        response = connection.getresponse()
        data = response.read()
        result_headers = dict(response.getheaders())
        status = response.status
        connection.close()
        return status, data, result_headers

    def create_run(self, mode="rehearsal"):
        status, data, _ = self.request("POST", "/api/runs", {"mode": mode})
        self.assertEqual(status, 201)
        return json.loads(data)["id"]

    def test_page_bootstraps_an_httponly_samesite_session(self):
        status, data, headers = self.request("GET", "/", role=None)
        self.assertEqual(status, 200)
        self.assertIn(b"Countermand", data)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_static_modules_have_javascript_mime_types(self):
        for asset in ("/app.js", "/view.js"):
            status, _, headers = self.request("GET", asset, role=None)
            self.assertEqual(status, 200)
            self.assertIn("javascript", headers["Content-Type"])

    def test_unauthenticated_api_is_refused(self):
        status, _, _ = self.request("GET", "/api/runs", role=None)
        self.assertEqual(status, 403)

    def test_health_does_not_claim_switch_is_connected(self):
        status, data, _ = self.request("GET", "/health", role=None)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(data)["switch_connected"])

    def test_agent_cannot_create_run_or_impersonate_owner(self):
        status, _, _ = self.request("POST", "/api/runs", {}, role="sales")
        self.assertEqual(status, 403)
        run_id = self.create_run()
        status, _, _ = self.request("POST", f"/api/runs/{run_id}/actions",
                                   {"kind": "discount", "owner": "sales"}, role="operations")
        self.assertEqual(status, 403)

    def test_agent_cannot_approve_its_own_recovery(self):
        run_id = self.create_run()
        self.request("POST", f"/api/runs/{run_id}/actions",
                     {"kind": "discount"}, role="sales")
        _, data, _ = self.request("POST", f"/api/runs/{run_id}/plans", {}, role="sales")
        plan = json.loads(data)["plan"]
        status, _, _ = self.request("POST", f"/api/plans/{plan['id']}/approve",
                                   {"digest": plan["digest"]}, role="sales")
        self.assertEqual(status, 403)

    def test_cross_origin_cookie_mutations_are_refused(self):
        status, _, _ = self.request("POST", "/api/runs", {}, role=None, extra={
            "Cookie": f"countermand_session={self.server.browser_session}",
            "Origin": "https://untrusted.example",
        })
        self.assertEqual(status, 403)

    def test_cookie_requires_origin_but_same_origin_is_allowed(self):
        headers = {"Cookie": f"countermand_session={self.server.browser_session}"}
        status, _, _ = self.request("POST", "/api/runs", {}, role=None, extra=headers)
        self.assertEqual(status, 403)
        headers["Origin"] = f"http://127.0.0.1:{self.port}"
        status, _, _ = self.request("POST", "/api/runs", {}, role=None, extra=headers)
        self.assertEqual(status, 201)

    def test_dns_rebinding_host_is_refused(self):
        status, _, _ = self.request("GET", "/health", role=None,
                                   extra={"Host": "untrusted.example"})
        self.assertEqual(status, 403)

    def test_external_mode_disables_human_adapter_impersonation(self):
        run_id = self.create_run("switch")
        status, _, _ = self.request("POST", f"/api/runs/{run_id}/actions",
                                   {"kind": "discount", "owner": "sales"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", f"/api/runs/{run_id}/actions",
                                   {"kind": "discount"}, role="sales")
        self.assertEqual(status, 200)

    def test_complete_browser_api_workflow(self):
        run_id = self.create_run()
        for kind, owner in (("discount", "sales"), ("invoice", "operations"),
                            ("message", "operations")):
            status, _, _ = self.request("POST", f"/api/runs/{run_id}/actions",
                                       {"kind": kind, "owner": owner})
            self.assertEqual(status, 200)
        self.request("POST", f"/api/runs/{run_id}/human-edit",
                     {"field": "contact", "value": "Maya Chen"})
        _, data, _ = self.request("POST", f"/api/runs/{run_id}/plans", {})
        plan = json.loads(data)["plan"]
        payload = {"digest": plan["digest"]}
        self.assertEqual(self.request("POST", f"/api/plans/{plan['id']}/approve",
                                      payload)[0], 200)
        for owner in ("sales", "operations"):
            status, _, _ = self.request("POST", f"/api/plans/{plan['id']}/execute",
                                       {**payload, "owner": owner})
            self.assertEqual(status, 200)
        status, data, _ = self.request("GET", f"/api/runs/{run_id}/evidence")
        self.assertEqual(status, 200)
        evidence = json.loads(data)
        self.assertTrue(evidence["verification"]["all_supported_repairs_verified"])
        self.assertFalse(evidence["verification"]["fully_reversed"])
        self.assertEqual(evidence["workflow"]["resources"]["crm"]["contact"], "Maya Chen")
        self.assertNotIn(self.server.keys["sales"], data.decode())

    def test_state_change_returns_http_conflict(self):
        run_id = self.create_run()
        self.request("POST", f"/api/runs/{run_id}/actions",
                     {"kind": "discount", "owner": "sales"})
        _, data, _ = self.request("POST", f"/api/runs/{run_id}/plans", {})
        plan = json.loads(data)["plan"]
        self.request("POST", f"/api/runs/{run_id}/human-edit",
                     {"field": "discount", "value": 12})
        status, data, _ = self.request("POST", f"/api/plans/{plan['id']}/approve",
                                      {"digest": plan["digest"]})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(data)["code"], "stale_plan")

    def test_mcp_tools_reach_the_real_api_and_cannot_escalate_their_role(self):
        run_id = self.create_run("switch")
        base = f"http://127.0.0.1:{self.port}"
        sales = Adapter(base, self.server.keys["sales"], "sales")
        result = sales.call("apply_demo_discount", {"run_id": run_id})
        self.assertEqual(result["resources"]["crm"]["discount"], 30)
        impersonator = Adapter(base, self.server.keys["sales"], "operations")
        with self.assertRaisesRegex(ValueError, "does not own"):
            impersonator.call("create_demo_invoice", {"run_id": run_id})
        operations = Adapter(base, self.server.keys["operations"], "operations")
        result = operations.call("create_demo_invoice", {"run_id": run_id})
        self.assertEqual(result["resources"]["billing"]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
