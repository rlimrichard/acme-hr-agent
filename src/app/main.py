"""FastAPI entry point for the three-workflow Acme HR agent."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.agent.orchestrator import HRAgent, MCPClient

app = FastAPI(title="Acme HR Agent", version="0.1.0")


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
    except httpx.HTTPError:
        tool_count, connected = 0, False
    return {"status": "ok" if connected else "degraded", "mcp_connected": connected,
            "chroma_loaded": False, "doc_count": 0, "tool_count": tool_count, "version": app.version}


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        return HRAgent(MCPClient()).answer(request.query, request.employee_id, request.confirmed).as_dict()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="The HR tool server is unavailable. Please try again shortly.") from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html><title>Acme HR Agent</title><h1>Acme HR Agent</h1><p>Ask about PTO, remote-work eligibility, or expense reimbursement via <code>POST /chat</code>.</p>"""
