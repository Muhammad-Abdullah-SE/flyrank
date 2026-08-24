"""Test suite - "the scary cases covered, deterministic, runnable in one command".

Runs against a throwaway SQLite database and an ephemeral HTTP server.
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

# Point the app at a temp DB BEFORE importing it
_tmpdir = tempfile.TemporaryDirectory()
os.environ["FLYRANK_DB"] = str(Path(_tmpdir.name) / "test.db")

from flyrank import db, scheduler  # noqa: E402
from flyrank.app import create_server  # noqa: E402

from scripts import seed  # noqa: E402


class FlyRankAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.seed()  # deterministic demo data into the temp DB
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        db.close_all()
        _tmpdir.cleanup()

    # ---------- helpers ----------
    def request(self, method, path, body=None, token=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        if body is not None:
            h["Content-Type"] = "application/json"
            payload = json.dumps(body)
        else:
            payload = None
        if token:
            h["Authorization"] = "Bearer " + token
        conn.request(method, path, body=payload, headers=h)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        ctype = res.getheader("Content-Type", "")
        if ctype.startswith("application/json") and raw:
            data = json.loads(raw.decode("utf-8"))
        else:
            data = raw if raw else None
        return res.status, data, res

    def register(self, email="tester@example.com", password="supersecret1", name="Tester"):
        return self.request("POST", "/api/auth/register", {"email": email, "password": password, "name": name})

    def login(self, email="tester@example.com", password="supersecret1"):
        return self.request("POST", "/api/auth/login", {"email": email, "password": password})

    # ---------- health ----------
    def test_health_lists_concepts(self):
        status, data, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(len(data["concepts"]), 5)

    # ---------- auth ----------
    def test_register_login_flow(self):
        status, data, _ = self.register("flow@example.com", "password123", "Flow")
        self.assertEqual(status, 201)
        self.assertIn("token", data)
        token = data["token"]

        status, data, _ = self.request("GET", "/api/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["email"], "flow@example.com")

        status, _, _ = self.login("flow@example.com", "wrongpass")
        self.assertEqual(status, 401)

        status, data, _ = self.login("flow@example.com", "password123")
        self.assertEqual(status, 200)
        self.assertIn("token", data)

    def test_protected_route_without_token(self):
        status, _, _ = self.request("GET", "/api/me")
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/api/reports/weekly")
        self.assertEqual(status, 401)

    def test_logout_revokes_token(self):
        status, data, _ = self.register("out@example.com", "password123", "Out")
        token = data["token"]
        status, _, _ = self.request("POST", "/api/auth/logout", token=token)
        self.assertEqual(status, 204)
        status, _, _ = self.request("GET", "/api/me", token=token)
        self.assertEqual(status, 401)

    def test_duplicate_email_conflict(self):
        status, _, _ = self.register("dup@example.com", "password123", "Dup")
        self.assertEqual(status, 201)
        status, _, _ = self.register("dup@example.com", "password123", "Dup2")
        self.assertEqual(status, 409)

    def test_validation_errors(self):
        status, data, _ = self.register("not-an-email", "password123", "X")
        self.assertEqual(status, 400)
        status, data, _ = self.register("ok@example.com", "short", "X")
        self.assertEqual(status, 400)
        status, data, _ = self.register("ok2@example.com", "password123", "X")
        self.assertEqual(status, 400)

    # ---------- deals ----------
    def test_deals_list_ranked_and_cached(self):
        status, data, res = self.request("GET", "/api/deals?limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(len(data["deals"]), 0)
        self.assertEqual(res.getheader("X-Cache"), "MISS")
        # first deal should have rank 1 and a score
        self.assertEqual(data["deals"][0]["rank"], 1)
        self.assertIn("value_score", data["deals"][0])

        status, data2, res2 = self.request("GET", "/api/deals?limit=10")
        self.assertEqual(res2.getheader("X-Cache"), "HIT")
        self.assertEqual(data["deals"][0]["id"], data2["deals"][0]["id"])

    def test_deals_filters_and_search(self):
        status, data, _ = self.request("GET", "/api/deals?origin=LHR&sort=price")
        self.assertEqual(status, 200)
        self.assertTrue(all(d["origin"] == "LHR" for d in data["deals"]))
        prices = [d["price"] for d in data["deals"]]
        self.assertEqual(prices, sorted(prices))

        status, data, _ = self.request("GET", "/api/deals/search?q=emirates")
        self.assertEqual(status, 200)
        self.assertGreater(len(data["deals"]), 0)
        self.assertTrue(all("emirates" in d["airline"].lower() for d in data["deals"]))

    def test_invalid_sort_and_bad_query(self):
        status, _, _ = self.request("GET", "/api/deals?sort=bogus")
        self.assertEqual(status, 400)
        status, _, _ = self.request("GET", "/api/deals/search?q=a")
        self.assertEqual(status, 400)

    def test_404_and_405(self):
        status, _, _ = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)
        status, _, _ = self.request("GET", "/api/jobs")  # unauthenticated -> 401
        self.assertEqual(status, 401)

    # ---------- watchlist ----------
    def test_watchlist_protected_flow(self):
        status, data, _ = self.register("watch@example.com", "password123", "Watch")
        token = data["token"]
        deal_id = 1
        status, _, _ = self.request("POST", f"/api/deals/{deal_id}/watch", token=token)
        self.assertEqual(status, 201)
        status, data, _ = self.request("GET", "/api/watchlist", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["deals"][0]["id"], deal_id)
        status, _, _ = self.request("DELETE", f"/api/deals/{deal_id}/watch", token=token)
        self.assertEqual(status, 204)
        status, data, _ = self.request("GET", "/api/watchlist", token=token)
        self.assertEqual(data["deals"], [])

    # ---------- reporting ----------
    def test_weekly_pdf_report(self):
        status, data, res = self.register("pdf@example.com", "password123", "Pdf")
        token = data["token"]
        status, raw_bytes, res = self.request("GET", "/api/reports/weekly", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(res.getheader("Content-Type"), "application/pdf")
        self.assertTrue(raw_bytes.startswith(b"%PDF-1.4"))
        self.assertIn(b"endstream", raw_bytes)
        self.assertIn(b"%%EOF", raw_bytes)

    # ---------- background jobs ----------
    def test_trigger_refresh_job(self):
        status, data, _ = self.register("job@example.com", "password123", "Job")
        token = data["token"]
        before = db.query_one("SELECT COUNT(*) AS n FROM price_history")["n"]
        status, _, _ = self.request("POST", "/api/jobs/refresh", token=token)
        self.assertEqual(status, 202)
        # job runs in a background thread; wait until the newest job finishes
        import time
        for _ in range(100):
            time.sleep(0.1)
            newest = db.query_one("SELECT status FROM jobs ORDER BY id DESC LIMIT 1")
            if newest and newest["status"] == "ok":
                break
        after = db.query_one("SELECT COUNT(*) AS n FROM price_history")["n"]
        self.assertGreater(after, before)
        self.assertEqual(newest["status"], "ok")
        status, data, _ = self.request("GET", "/api/jobs", token=token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(data["jobs"]), 1)

    def test_scheduler_cron_logic(self):
        from datetime import datetime
        self.assertTrue(scheduler._cron_matches("30 8 * * *", datetime(2026, 8, 24, 8, 30)))
        self.assertFalse(scheduler._cron_matches("30 8 * * *", datetime(2026, 8, 24, 8, 31)))
        self.assertTrue(scheduler._cron_matches("*/15 * * * *", datetime(2026, 8, 24, 10, 45)))

    # ---------- LLM (local fallback + cost log) ----------
    def test_summarize_logs_cost(self):
        status, data, _ = self.register("llm@example.com", "password123", "Llm")
        token = data["token"]
        status, data, _ = self.request("POST", "/api/deals/summarize", {"limit_top": 5}, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["source"], "local")  # no API key in tests
        self.assertIn("$", data["summary"])

        row = db.query_one("SELECT * FROM ai_logs WHERE user_id = (SELECT id FROM users WHERE email = 'llm@example.com') ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(row)
        self.assertEqual(row["endpoint"], "/api/deals/summarize")

    def test_summarize_validation(self):
        status, data, _ = self.register("llmval@example.com", "password123", "Llmv")
        token = data["token"]
        status, _, _ = self.request("POST", "/api/deals/summarize", {"deals": []}, token=token)
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/api/deals/summarize", {
            "deals": [{"airline": "X", "origin": "LHR", "destination": "JFK", "price": -5}]
        }, token=token)
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)