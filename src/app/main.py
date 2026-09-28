"""FastAPI entry point for the three-workflow Acme HR agent."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.agent.orchestrator import HRAgent, MCPClient

_mcp_proc: subprocess.Popen | None = None


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
        from src.rag.retrieval import _collection
        chroma_loaded = _collection is not None
        doc_count = _collection.count() if chroma_loaded else 0
    except Exception:
        chroma_loaded, doc_count = False, 0
    return {"status": "ok" if connected else "degraded", "mcp_connected": connected,
            "chroma_loaded": chroma_loaded, "doc_count": doc_count, "tool_count": tool_count, "version": app.version}


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        return HRAgent(MCPClient()).answer(request.query, request.employee_id, request.confirmed).as_dict()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="The HR tool server is unavailable. Please try again shortly.") from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html><title>Acme HR Agent</title><h1>Acme HR Agent</h1><p>Ask about PTO, remote-work eligibility, or expense reimbursement via <code>POST /chat</code>.</p>"""
