"""FastAPI entry point for the Acme HR policy and workflow agent."""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from src.agent.orchestrator import HRAgent, MCPClient
from src.agent.reasoner import assess_answer_confidence
from src.app import portal

_mcp_proc: subprocess.Popen | None = None

# ── ADDED: admin authentication ───────────────────────────────────────────
# Protects /admin and /admin/* (logs, tickets) -- previously these had no
# authentication at all, which is a real problem once deployed to a public
# URL (they expose employee chat history and HR tickets).
#
# ADMIN_PASSWORD has NO default -- if it isn't set, login is impossible
# (fails closed) rather than falling back to a guessable default password.
# SESSION_SECRET falls back to a random value generated at process start if
# not set in the environment; this means existing sessions are invalidated
# on every restart, which is an acceptable tradeoff for "fails safe" over
# "fails with a hardcoded secret committed to the repo."
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # required — see login handler below
_SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
if not os.getenv("SESSION_SECRET"):
    print("WARNING: SESSION_SECRET not set in environment — using a random "
          "value for this process only. Admin sessions will not survive a "
          "restart. Set SESSION_SECRET in .env / production env vars to "
          "avoid this.")
if not ADMIN_PASSWORD:
    print("WARNING: ADMIN_PASSWORD not set — the admin panel login is "
          "disabled until it is set (login will always fail).")

_ADMIN_COOKIE_NAME = "admin_session"
_ADMIN_SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours
_admin_serializer = URLSafeTimedSerializer(_SESSION_SECRET, salt="admin-session")
_employee_serializer = URLSafeTimedSerializer(_SESSION_SECRET, salt="employee-session")
_EMPLOYEE_COOKIE = "employee_session"


def _is_admin_authenticated(request: Request) -> bool:
    token = request.cookies.get(_ADMIN_COOKIE_NAME)
    if not token:
        return False
    try:
        _admin_serializer.loads(token, max_age=_ADMIN_SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_admin_api(request: Request) -> None:
    """Dependency for JSON admin endpoints (logs, tickets) -- returns a
    clean 401 so admin.js's fetch calls can detect it and redirect to
    /admin/login, rather than the page silently rendering empty data."""
    if not _is_admin_authenticated(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

_LOG_DIR = Path(__file__).parents[2] / "logs"
_REGRESSION_RESULTS_FILE = _LOG_DIR / "latest_regression_tests.json"
_CHROMA_SQLITE = Path(__file__).parents[2] / "chroma_db" / "chroma.sqlite3"
_EMPLOYEES_FILE = Path(__file__).parents[2] / "data" / "employees.json"


def _quoted_sql_identifier(name: str) -> str:
    """Quote a SQLite identifier sourced from sqlite_master, never user SQL."""
    return '"' + name.replace('"', '""') + '"'


def _database_tables() -> list[str]:
    if not _CHROMA_SQLITE.is_file():
        raise HTTPException(status_code=404, detail="Policy database is not available")
    with sqlite3.connect(f"file:{_CHROMA_SQLITE}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [str(row[0]) for row in rows]


def _safe_database_value(value: Any) -> Any:
    """Keep admin previews useful without returning large binary/vector payloads."""
    if isinstance(value, bytes):
        return f"<binary: {len(value)} bytes>"
    if isinstance(value, str) and len(value) > 600:
        return value[:600] + "…"
    return value


def _employee_records() -> list[dict[str, Any]]:
    if not _EMPLOYEES_FILE.is_file():
        raise HTTPException(status_code=404, detail="HR employee directory is not available")
    try:
        return json.loads(_EMPLOYEES_FILE.read_text(encoding="utf-8")).get("employees", [])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="HR employee directory is invalid") from exc


def _bounded_audit_value(value: Any, max_string: int = 12_000) -> Any:
    """Keep admin audit records detailed without letting one call grow logs unbounded."""
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + "\n… [truncated for audit storage]"
    if isinstance(value, dict):
        return {key: _bounded_audit_value(item, max_string) for key, item in value.items()}
    if isinstance(value, list):
        return [_bounded_audit_value(item, max_string) for item in value]
    return value


def _answer_confidence(query: str, result: dict[str, Any]) -> dict[str, Any]:
    """Record a score only when its assessment method actually ran."""
    routing = result.get("llm_reasoning", {}).get("routing", {})
    if routing.get("selected_workflow") == "help":
        return {
            "score": 100,
            "status": "scored",
            "method": "Deterministic capability intent and response",
            "reason": "The question matched the help route and received the defined capability response.",
            "note": "Intent match only; not a calibrated probability of correctness.",
        }
    if routing.get("route_source") != "llm":
        return {
            "score": None,
            "status": "not_evaluated",
            "method": "LLM relevance and evidence review",
            "note": "No valid LLM route was recorded, so answer review was skipped.",
        }
    return assess_answer_confidence(query, result.get("answer", ""), result.get("tool_trace", []))


def _log_chat(employee_id: str, query: str, result: dict[str, Any], confirmed: bool = False) -> None:
    try:
        _LOG_DIR.mkdir(exist_ok=True)
        now = datetime.now(timezone.utc)
        log_file = _LOG_DIR / f"{now.strftime('%Y-%m-%d')}.jsonl"
        entry = {
            "timestamp": now.isoformat(timespec="seconds"),
            "employee_id": employee_id,
            "query": query,
            "answer": result.get("answer", ""),
            "confirmed": confirmed,
            "requires_confirmation": result.get("requires_confirmation", False),
            "created_ticket_ids": [
                step.get("result", {}).get("ticket_id")
                for step in result.get("tool_trace", [])
                if step.get("tool") == "create_mock_hr_ticket" and step.get("result", {}).get("ticket_id")
            ],
            "confidence": _bounded_audit_value(_answer_confidence(query, result)),
            "escalated": result.get("escalated", False),
            "tool_steps": len(result.get("tool_trace", [])),
            # Admin-only, bounded diagnostic detail. API keys are never part
            # of a prompt or MCP response and are not written here.
            "llm_reasoning": _bounded_audit_value(result.get("llm_reasoning", {})),
            "tool_trace": _bounded_audit_value(result.get("tool_trace", [])),
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never break the chat response


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mcp_proc
    mcp_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001")
    # Only auto-start if pointing at localhost (not an external URL)
    if "127.0.0.1" in mcp_url or "localhost" in mcp_url:
        _mcp_proc = subprocess.Popen(
            [sys.executable, "-m", "src.mcp.server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give the server up to 10 s to become ready
        for _ in range(20):
            try:
                httpx.get(f"{mcp_url.rstrip('/')}/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.5)
    # Pre-warm the embedding model and ChromaDB so the first /chat request is fast
    try:
        from src.mcp.server import search_policy_documents
        search_policy_documents("warmup", top_k=1)
    except Exception:
        pass  # non-fatal — warmup failure doesn't block startup

    yield
    if _mcp_proc is not None:
        _mcp_proc.terminate()


app = FastAPI(title="Acme HR Agent", version="0.1.0", lifespan=lifespan)

# ── ADDED: serve the chat UI's static assets ──────────────────────────────
STATIC_DIR   = Path(__file__).parent / "static"
POLICIES_DIR = Path(__file__).parents[2] / "data" / "policies"
_TICKETS_FILE = Path(__file__).parents[2] / "data" / "tickets.jsonl"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_CONTENT_TYPES = {
    ".pdf":  "application/pdf",
    ".html": "text/html",
    ".md":   "text/plain",
    ".txt":  "text/plain",
}

def _read_text_for_meta(path: Path) -> str:
    if path.suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join(p.extract_text() or "" for p in reader.pages[:2])
        except Exception:
            return ""
    return path.read_text(encoding="utf-8", errors="replace")

def _doc_meta(path: Path) -> dict[str, Any]:
    text    = _read_text_for_meta(path)
    doc_id  = re.search(r"POL-[A-Z]+-\d+", text)
    title_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if not title_m:
        title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", text, re.IGNORECASE)
    stem    = path.stem.replace("_", " ").title()
    return {
        "filename": path.name,
        "title":    title_m.group(1).strip() if title_m else stem,
        "doc_id":   doc_id.group(0) if doc_id else path.stem.upper(),
        "format":   path.suffix.lstrip("."),
        "size_kb":  round(path.stat().st_size / 1024, 1),
        "url":      f"/documents/{path.name}",
    }


class ChatRequest(BaseModel):
    query: str = Field(min_length=3)
    employee_id: str = Field(pattern=r"^EMP-\d{3}$")
    confirmed: bool = False
    top_k: int = Field(default=5, ge=1, le=20)


class ReviewRequest(BaseModel):
    decision: str
    message: str = Field(min_length=1, max_length=4000)


def _signed_in_employee(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(_EMPLOYEE_COOKIE)
    if not token:
        return None
    try:
        employee_id = _employee_serializer.loads(token, max_age=60 * 60 * 12).get("employee_id")
    except (BadSignature, SignatureExpired, AttributeError):
        return None
    return next((person for person in _employee_records() if person["employee_id"] == employee_id), None)


def require_employee(request: Request) -> dict[str, Any]:
    person = _signed_in_employee(request)
    if not person:
        raise HTTPException(status_code=401, detail="Please sign in")
    return person


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlsplit
        origin_host = urlsplit(origin).netloc
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if origin_host != host:
            raise HTTPException(status_code=403, detail="Invalid request origin")


@app.get("/login")
def employee_login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "employee-login.html")


@app.post("/login")
def employee_login(request: Request, employee_id: str = Form(...), password: str = Form(...)) -> Response:
    _same_origin(request)
    employee_id = employee_id.strip().upper()
    if not portal.authenticate(employee_id, password, _EMPLOYEES_FILE):
        return JSONResponse(status_code=401, content={"ok": False, "detail": "Invalid employee ID or password"})
    response = JSONResponse({"ok": True})
    response.set_cookie(_EMPLOYEE_COOKIE, _employee_serializer.dumps({"employee_id": employee_id}),
                        max_age=60 * 60 * 12, httponly=True, samesite="lax",
                        secure=(request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"))
    return response


@app.post("/logout")
def employee_logout(request: Request) -> Response:
    _same_origin(request)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(_EMPLOYEE_COOKIE)
    return response


@app.get("/portal/me")
def portal_me(person: dict[str, Any] = Depends(require_employee)) -> dict[str, Any]:
    records = _employee_records()
    return {"employee_id": person["employee_id"], "name": person["name"],
            "department": person["department"], "is_hr": person["department"] == "People Operations",
            "is_manager": any(item.get("manager_id") == person["employee_id"] for item in records)}


@app.get("/portal/tickets")
def portal_tickets(person: dict[str, Any] = Depends(require_employee)) -> dict[str, Any]:
    tickets = portal.all_tickets(_EMPLOYEES_FILE)
    own = [item for item in tickets if item.get("employee_id") == person["employee_id"]]
    queue = [item for item in tickets if item.get("status") in ("created", "pending")
             and portal.can_review(person, item, _EMPLOYEES_FILE)]
    return {"my_pending": [item for item in own if item.get("status") in ("created", "pending")],
            "my_closed": [item for item in own if item.get("status") in ("approved", "denied")],
            "hr_queue": [item for item in queue if item.get("ticket_type") != "pto_request"],
            "manager_queue": [item for item in queue if item.get("ticket_type") == "pto_request"]}


@app.post("/portal/tickets/{ticket_id}/review")
def portal_review(ticket_id: str, body: ReviewRequest, request: Request,
                  person: dict[str, Any] = Depends(require_employee)) -> dict[str, Any]:
    _same_origin(request)
    try:
        return portal.review_ticket(ticket_id, person, body.decision, body.message, _EMPLOYEES_FILE)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/portal")
def portal_page(request: Request) -> Response:
    if not _signed_in_employee(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC_DIR / "portal.html")


@app.get("/health")
def health() -> dict[str, Any]:
    base_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001").rstrip("/")
    try:
        tool_count = len(MCPClient(base_url).discover_tools())
        connected = tool_count >= 5
    except Exception:
        tool_count, connected = 0, False
    try:
        from src.rag import retrieval as _rag
        _rag._get_collection()
        chroma_loaded = _rag._collection is not None
        doc_count = _rag._collection.count() if chroma_loaded else 0
    except Exception:
        chroma_loaded, doc_count = False, 0
    return {"status": "ok" if connected else "degraded", "mcp_connected": connected,
            "chroma_loaded": chroma_loaded, "doc_count": doc_count, "tool_count": tool_count, "version": app.version}


@app.post("/chat")
def chat(request: ChatRequest, http_request: Request, person: dict[str, Any] = Depends(require_employee)) -> dict[str, Any]:
    _same_origin(http_request)
    if request.employee_id != person["employee_id"]:
        raise HTTPException(status_code=403, detail="Employee ID does not match signed-in account")
    try:
        agent = HRAgent(MCPClient())
        agent.top_k = request.top_k
        result = agent.answer(request.query, request.employee_id, request.confirmed).as_dict()
        _log_chat(request.employee_id, request.query, result, request.confirmed)
        # The sanitized audit data is written only to the authenticated admin
        # log; employee-facing API clients must not receive it.
        result.pop("llm_reasoning", None)
        return result
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail="The HR tool server is unavailable. Please try again shortly.") from exc


@app.get("/employees")
def employee_options(_person: dict[str, Any] = Depends(require_employee)) -> dict[str, list[dict[str, str]]]:
    """Minimal employee directory for the home-page account selector."""
    employees = [
        {"employee_id": employee["employee_id"], "name": employee["name"]}
        for employee in _employee_records()
    ]
    return {"employees": sorted(employees, key=lambda employee: employee["employee_id"])}


# ── CHANGED: was a hardcoded HTML string, now serves the real chat UI ────
@app.get("/documents")
def list_documents() -> dict[str, Any]:
    docs = sorted(
        [_doc_meta(p) for p in POLICIES_DIR.iterdir() if p.suffix in _CONTENT_TYPES],
        key=lambda d: d["doc_id"],
    )
    return {"documents": docs}

@app.get("/documents/{filename}")
def get_document(filename: str) -> FileResponse:
    path = POLICIES_DIR / filename
    if not path.exists() or path.suffix not in _CONTENT_TYPES:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(
        path,
        media_type=_CONTENT_TYPES[path.suffix],
        headers={"Content-Disposition": "inline"},
    )

@app.get("/hr-docs")
def docs_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "documents.html")

# ── ADDED: admin login/logout ─────────────────────────────────────────────
@app.get("/admin/login")
def admin_login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin-login.html")


@app.post("/admin/login")
def admin_login_submit(request: Request, username: str = Form(...), password: str = Form(...)) -> Response:
    valid = (
        ADMIN_PASSWORD is not None
        and secrets.compare_digest(username, ADMIN_USERNAME)
        and secrets.compare_digest(password, ADMIN_PASSWORD)
    )
    if not valid:
        return JSONResponse(status_code=401, content={"ok": False})

    token = _admin_serializer.dumps({"u": username})
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        _ADMIN_COOKIE_NAME, token,
        max_age=_ADMIN_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=(request.url.scheme == "https"),  # auto: plain http locally, forced https in prod (behind nginx/TLS)
    )
    return response


@app.get("/admin/logout")
def admin_logout() -> Response:
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(_ADMIN_COOKIE_NAME)
    return response


# ── CHANGED: all four routes below now require an authenticated admin session ──
@app.get("/admin")
def admin_page(request: Request) -> Response:
    if not _is_admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return FileResponse(STATIC_DIR / "admin.html")

@app.get("/admin/logs")
def list_log_dates(_admin: None = Depends(require_admin_api)) -> dict[str, Any]:
    if not _LOG_DIR.exists():
        return {"dates": []}
    dates = sorted(
        [p.stem for p in _LOG_DIR.glob("*.jsonl") if re.match(r"^\d{4}-\d{2}-\d{2}$", p.stem)],
        reverse=True,
    )
    return {"dates": dates}

@app.get("/admin/tickets")
def list_tickets(_admin: None = Depends(require_admin_api)) -> dict[str, Any]:
    if not _TICKETS_FILE.exists():
        return {"tickets": []}
    tickets = []
    for line in _TICKETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                tickets.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return {"tickets": list(reversed(tickets))}


@app.get("/admin/regression-tests")
def regression_test_results(_admin: None = Depends(require_admin_api)) -> dict[str, Any]:
    """Return the most recent persisted regression-test run for the admin UI."""
    if not _REGRESSION_RESULTS_FILE.is_file():
        return {"available": False}
    try:
        result = json.loads(_REGRESSION_RESULTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"available": False}
    return {"available": True, **_bounded_audit_value(result)}


@app.get("/admin/database")
def database_overview(_admin: None = Depends(require_admin_api)) -> dict[str, Any]:
    """Return read-only Chroma SQLite table metadata for the admin browser."""
    tables = _database_tables()
    with sqlite3.connect(f"file:{_CHROMA_SQLITE}?mode=ro", uri=True) as connection:
        overview = [
            {
                "name": table,
                "row_count": connection.execute(
                    f"SELECT COUNT(*) FROM {_quoted_sql_identifier(table)}"
                ).fetchone()[0],
            }
            for table in tables
        ]
    return {"database": _CHROMA_SQLITE.name, "read_only": True, "tables": overview}


@app.get("/admin/hr-database")
def hr_database(_admin: None = Depends(require_admin_api)) -> dict[str, Any]:
    """Return the read-only HR employee directory used by the agent."""
    records = _employee_records()
    columns = [
        "employee_id", "name", "role", "department", "office_location",
        "remote_status", "hire_date", "manager_id", "pto_balance_days",
    ]
    employees = [{column: employee.get(column) for column in columns} for employee in records]
    return {"source": _EMPLOYEES_FILE.name, "read_only": True, "columns": columns, "employees": employees}


@app.get("/admin/database/{table_name}")
def database_table_rows(
    table_name: str,
    limit: int = Query(default=50, ge=1, le=100),
    _admin: None = Depends(require_admin_api),
) -> dict[str, Any]:
    """Return a capped, read-only row preview for one known SQLite table."""
    if table_name not in _database_tables():
        raise HTTPException(status_code=404, detail="Database table not found")
    identifier = _quoted_sql_identifier(table_name)
    with sqlite3.connect(f"file:{_CHROMA_SQLITE}?mode=ro", uri=True) as connection:
        cursor = connection.execute(f"SELECT * FROM {identifier} LIMIT ?", (limit,))
        columns = [column[0] for column in cursor.description]
        rows = [
            {column: _safe_database_value(value) for column, value in zip(columns, row)}
            for row in cursor.fetchall()
        ]
    return {"table": table_name, "columns": columns, "rows": rows, "limit": limit}

@app.get("/admin/logs/{date}")
def get_log_entries(date: str, _admin: None = Depends(require_admin_api)) -> dict[str, Any]:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=400, detail="Invalid date format")
    log_file = _LOG_DIR / f"{date}.jsonl"
    if not log_file.exists():
        return {"date": date, "entries": []}
    entries = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return {"date": date, "entries": list(reversed(entries))}

@app.get("/")
def index(request: Request) -> Response:
    if not _signed_in_employee(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC_DIR / "index.html")
