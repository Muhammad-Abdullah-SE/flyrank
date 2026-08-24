"""FlyRank HTTP API + static file server (concept: API ENDPOINTS).

Dependency-free REST API built on http.server:

  POST   /api/auth/register   201  register + session token
  POST   /api/auth/login      200  login  + session token
  POST   /api/auth/logout     204  revoke token            [auth]
  GET    /api/me              200  current user            [auth]
  GET    /api/deals           200  ranked deals (cached)
  GET    /api/deals/search    200  free-text search (cached)
  POST   /api/deals/<id>/watch 201 add deal to watchlist   [auth]
  DELETE /api/deals/<id>/watch 204 remove from watchlist   [auth]
  GET    /api/watchlist       200  your watched deals      [auth]
  POST   /api/deals/summarize 200  AI briefing + cost log  [auth]
  GET    /api/reports/weekly  200  weekly PDF report       [auth]
  GET    /api/jobs            200  recent job runs         [auth]
  POST   /api/jobs/refresh    202  trigger price refresh   [auth]
  GET    /api/health          200  liveness

Correct status codes (201/400/401/404/405/409/202), JSON validation, and
protected routes are all implemented here.
"""

from __future__ import annotations

import json
import os
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import auth, cache, db, deals, llm, reporting, scheduler

WEB_DIR = Path(__file__).resolve().parent / "web"
PORT_ENV = "FLYRANK_PORT"
HOST_ENV = "FLYRANK_HOST"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _json(data, status: int = 200, headers: dict | None = None):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    h = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))}
    h.update(headers or {})
    return status, body, h


def _error(message: str, status: int, code: str | None = None):
    return _json({"error": message, "code": code or "error"}, status)


def _not_found():
    return _error("not found", 404, "not_found")


def _method_not_allowed(allow: str):
    return _json(
        {"error": "method not allowed"}, 405, {"Allow": allow}
    )


# --------------------------------------------------------------------------
# Handlers. Each returns (status, body_bytes, headers).
# --------------------------------------------------------------------------
def route(method: str, path: str, body: dict | None, user: dict | None, query: dict, handler) -> tuple:
    # --- auth ---
    if method == "POST" and path == "/api/auth/register":
        email = (body or {}).get("email", "")
        password = (body or {}).get("password", "")
        name = (body or {}).get("name", "")
        if not EMAIL_RE.match(email):
            return _error("valid email required", 400, "validation")
        if not isinstance(password, str) or len(password) < 8:
            return _error("password must be at least 8 characters", 400, "validation")
        if not name or not isinstance(name, str) or len(name.strip()) < 2:
            return _error("name is required (min 2 characters)", 400, "validation")
        try:
            result = auth.register(email, password, name)
        except ValueError as exc:
            return _error(str(exc), 409, "conflict")
        return _json(result, 201)

    if method == "POST" and path == "/api/auth/login":
        email = (body or {}).get("email", "")
        password = (body or {}).get("password", "")
        if not isinstance(email, str) or not isinstance(password, str):
            return _error("email and password required", 400, "validation")
        result = auth.login(email, password)
        if not result:
            return _error("invalid email or password", 401, "unauthorized")
        return _json(result, 200)

    if method == "POST" and path == "/api/auth/logout":
        if not user:
            return _error("authentication required", 401, "unauthorized")
        auth.revoke_session(handler.token)
        return _json({"ok": True}, 204)

    if method == "GET" and path == "/api/me":
        if not user:
            return _error("authentication required", 401, "unauthorized")
        return _json({"user": user})

    # --- deals (public reads, cached) ---
    if method == "GET" and path == "/api/deals":
        filters = {
            "origin": query.get("origin", [None])[0],
            "destination": query.get("destination", [None])[0],
            "airline": query.get("airline", [None])[0],
        }
        try:
            max_price = float(query.get("max_price", [""])[0]) if query.get("max_price", [""])[0] else None
        except ValueError:
            return _error("max_price must be a number", 400, "validation")
        filters["max_price"] = max_price
        sort = query.get("sort", ["value"])[0]
        if sort not in deals.SORTS:
            return _error(f"sort must be one of {list(deals.SORTS)}", 400, "validation")
        try:
            limit = int(query.get("limit", ["50"])[0])
        except ValueError:
            return _error("limit must be an integer", 400, "validation")
        limit = max(1, min(limit, 100))
        result, hit = deals.list_deals(filters, sort, limit)
        return _json(
            {"deals": result, "total": len(result), "cache": "HIT" if hit else "MISS", "sort": sort},
            200,
            {"X-Cache": "HIT" if hit else "MISS"},
        )

    if method == "GET" and path == "/api/deals/search":
        q = query.get("q", [""])[0]
        if not q or len(q) < 2:
            return _error("q must be at least 2 characters", 400, "validation")
        if len(q) > 40:
            return _error("q too long (max 40)", 400, "validation")
        result, hit = deals.search_deals(q, 20)
        return _json(
            {"query": q, "deals": result, "total": len(result), "cache": "HIT" if hit else "MISS"},
            200,
            {"X-Cache": "HIT" if hit else "MISS"},
        )

    # watchlist endpoints: /api/deals/<id>/watch
    m = re.fullmatch(r"/api/deals/(\d+)/watch", path)
    if m and method in ("POST", "DELETE"):
        if not user:
            return _error("authentication required", 401, "unauthorized")
        deal_id = int(m.group(1))
        if method == "POST":
            try:
                deals.watch_deal(user["id"], deal_id)
            except ValueError:
                return _error("deal not found", 404, "not_found")
            return _json({"ok": True, "deal_id": deal_id}, 201)
        deals.unwatch_deal(user["id"], deal_id)
        return _json({"ok": True}, 204)

    if method == "GET" and path == "/api/watchlist":
        if not user:
            return _error("authentication required", 401, "unauthorized")
        return _json({"deals": deals.watchlist(user["id"])})

    # --- LLM (protected) ---
    if method == "POST" and path == "/api/deals/summarize":
        if not user:
            return _error("authentication required", 401, "unauthorized")
        payload = body or {}
        if isinstance(payload.get("deals"), list):
            deal_input = payload["deals"]
        else:
            filters = {
                "origin": payload.get("origin"),
                "destination": payload.get("destination"),
                "airline": payload.get("airline"),
                "max_price": payload.get("max_price"),
            }
            deal_input, _ = deals.list_deals(filters, "value", 15)
        try:
            summary = llm.summarize_deals(deal_input, user)
        except ValueError as exc:
            return _error(str(exc), 400, "validation")
        return _json(summary)

    # --- reporting (protected) ---
    if method == "GET" and path == "/api/reports/weekly":
        if not user:
            return _error("authentication required", 401, "unauthorized")
        all_deals, _ = deals.list_deals(None, "value", 20)
        pdf = reporting.build_weekly_report(user, all_deals)
        filename = f"flyrank-weekly-report-{user['id']}.pdf"
        return (
            200,
            pdf,
            {
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf)),
                "Cache-Control": "no-store",
            },
        )

    # --- jobs (protected) ---
    if method == "GET" and path == "/api/jobs":
        if not user:
            return _error("authentication required", 401, "unauthorized")
        return _json({"jobs": scheduler.recent_jobs(15)})

    if method == "POST" and path == "/api/jobs/refresh":
        if not user:
            return _error("authentication required", 401, "unauthorized")
        result = {"job_id": None}
        ev = threading.Event()

        def worker():
            try:
                out = scheduler.refresh_prices()
                result["job_id"] = out["job_id"]
            except Exception as exc:  # pragma: no cover - defensive
                result["job_id"] = -1
                result["error"] = str(exc)
            finally:
                ev.set()

        threading.Thread(target=worker, daemon=True).start()
        return _json({"accepted": True, "detail": "price refresh started in background"}, 202)

    # --- health ---
    if method == "GET" and path == "/api/health":
        return _json(
            {
                "status": "ok",
                "app": auth_app_name(),
                "version": auth_version(),
                "concepts": [
                    "api_endpoints",
                    "database",
                    "authentication",
                    "background_cron_jobs",
                    "reporting_pdf",
                    "caching",
                    "llm_integration",
                ],
            }
        )

    return None  # unhandled


def auth_app_name():
    from . import APP_NAME

    return APP_NAME


def auth_version():
    from . import __version__

    return __version__


class FlyRankHandler(BaseHTTPRequestHandler):
    server_version = "FlyRank/1.0"
    token: str | None = None

    # ---------- plumbing ----------
    def log_message(self, fmt, *args):
        print("[flyrank]", fmt % args)

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _handle(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=True)
        method = self.command

        # serve the SPA
        if method == "GET" and path in ("/", "/index.html", "/favicon.ico"):
            static = WEB_DIR / ("index.html" if path != "/favicon.ico" else "favicon.ico")
            if not static.exists() and path == "/favicon.ico":
                return self._respond(204, b"", {"Content-Length": "0"})
            return self._respond(200, static.read_bytes(), {"Content-Type": "text/html; charset=utf-8"})

        if not path.startswith("/api/"):
            return self._respond(*_not_found())

        # pull token from Authorization: Bearer ...
        token = None
        authz = self.headers.get("Authorization", "")
        if authz.lower().startswith("bearer "):
            token = authz[7:].strip()
        self.token = token
        user = auth.user_from_token(token) if token else None

        body = self._read_body() if method in ("POST", "PUT", "PATCH", "DELETE") else None
        if method in ("POST", "PUT", "PATCH") and self.headers.get("Content-Length") not in (None, "0"):
            if self.headers.get("Content-Type", "").startswith("application/json") and body is None:
                return self._respond(*_error("invalid JSON body", 400, "validation"))

        result = route(method, path, body, user, query, self)
        if result is None:
            if method == "GET":
                return self._respond(*_not_found())
            return self._respond(*_method_not_allowed("GET, POST, DELETE"))

        status, payload, headers = result
        if status == 204:
            headers = {"Content-Length": "0"}  # no entity headers on 204
            payload = b""
        return self._respond(status, payload, headers)

    def _respond(self, status: int, payload: bytes, headers: dict):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if payload and self.command != "HEAD":
            self.wfile.write(payload)

    def do_GET(self):
        try:
            self._handle()
        except BrokenPipeError:
            pass
        except Exception:
            traceback.print_exc()
            try:
                self._respond(*_error("internal server error", 500, "internal"))
            except Exception:
                pass

    def do_POST(self):
        self.do_GET()

    def do_DELETE(self):
        self.do_GET()

    def do_PUT(self):
        self.do_GET()

    def do_PATCH(self):
        self.do_GET()

    def do_HEAD(self):
        self.do_GET()


def create_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    db.init_db()
    host = host or os.environ.get(HOST_ENV, "127.0.0.1")
    port = port if port is not None else int(os.environ.get(PORT_ENV, "8000"))
    server = ThreadingHTTPServer((host, port), FlyRankHandler)
    return server


def main() -> None:
    import sys

    db.init_db()
    host = os.environ.get(HOST_ENV, "127.0.0.1")
    port = int(os.environ.get(PORT_ENV, "8000"))
    server = ThreadingHTTPServer((host, port), FlyRankHandler)
    # start the in-process cron scheduler
    sched = scheduler.SchedulerThread()
    sched.start()
    print(f"FlyRank running at http://{host}:{port}  (Ctrl+C to stop)")
    print(f"Database: {db.db_path()}")
    print("Demo login: demo@flyrank.dev / demo1234  (after running scripts/seed.py)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
        sched.stop()


if __name__ == "__main__":
    main()