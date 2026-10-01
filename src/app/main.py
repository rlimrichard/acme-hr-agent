"""FastAPI entry point for the three-workflow Acme HR agent."""

from __future__ import annotations

import json
import os
import re
import secrets
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
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from src.agent.orchestrator import HRAgent, MCPClient

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


def _log_chat(employee_id: str, query: str, result: dict[str, Any]) -> None:
    try:
        _LOG_DIR.mkdir(exist_ok=True)
        now = datetime.now(timezone.utc)
        log_file = _LOG_DIR / f"{now.strftime('%Y-%m-%d')}.jsonl"
        entry = {
            "timestamp": now.isoformat(timespec="seconds"),
            "employee_id": employee_id,
            "query": query,
            "answer": result.get("answer", ""),
            "escalated": result.get("escalated", False),
            "tool_steps": len(result.get("tool_trace", [])),
            # Admin-only audit metadata.  This deliberately excludes raw LLM
            # prompts, employee-profile values, policy text, and credentials.
            "llm_reasoning": result.get("llm_reasoning", {}),
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


@app.get("/health")
def health() -> dict[str, Any]:
    base_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001").rstrip("/")
    try:
        tool_count = len(httpx.get(f"{base_url}/tools", timeout=2).json().get("tools", []))
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
def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        result = HRAgent(MCPClient()).answer(request.query, request.employee_id, request.confirmed).as_dict()
        _log_chat(request.employee_id, request.query, result)
        return result
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="The HR tool server is unavailable. Please try again shortly.") from exc


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
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
