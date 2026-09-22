"""Local HTTP tool server for the Acme HR reasoning layer.

The agent only reaches HR data and retrieval through this service.  The
endpoints deliberately expose an inspectable, MCP-style tool boundary:
``GET /tools`` discovers schemas and ``POST /tools/{name}`` invokes a tool.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).parents[2]
DATA_FILE = ROOT / "data" / "employees.json"
SCHEMA_FILE = ROOT / "project_plan" / "mcp_tools_schema.json"
POLICIES_DIR = ROOT / "data" / "policies"

app = FastAPI(title="Acme HR MCP Tool Server", version="0.1.0")


def _tools() -> list[dict[str, Any]]:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["tools"]


def _employees() -> list[dict[str, Any]]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))["employees"]


def _employee(employee_id: str) -> dict[str, Any] | None:
    return next((item for item in _employees() if item["employee_id"] == employee_id), None)


def _citation_from_path(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    doc_id = re.search(r"POL-[A-Z]+-\d+", text)
    title = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return (doc_id.group(0) if doc_id else path.stem.upper(), title.group(1) if title else path.stem)


def _lexical_search(query: str, top_k: int, doc_id: str | None = None) -> list[dict[str, Any]]:
    """Small deterministic fallback used before Richard's Chroma index is built."""
    terms = {term.lower() for term in re.findall(r"[a-zA-Z]{3,}", query)}
    matches: list[dict[str, Any]] = []
    for policy in POLICIES_DIR.glob("*.md"):
        policy_id, title = _citation_from_path(policy)
        if doc_id and policy_id != doc_id:
            continue
        lines = policy.read_text(encoding="utf-8").splitlines()
        section = title
        for line_number, line in enumerate(lines):
            if line.startswith("#"):
                section = line.lstrip("#").strip()
            score = sum(term in line.lower() for term in terms)
            if score:
                window = " ".join(lines[max(0, line_number - 1):line_number + 3]).strip()
                matches.append({"doc_id": policy_id, "doc_title": title, "section": section,
                                "text": window, "snippet": window[:180], "score": score})
    return sorted(matches, key=lambda item: item["score"], reverse=True)[:top_k]


def _search(query: str, top_k: int = 5, doc_id: str | None = None) -> dict[str, Any]:
    try:
        from src.rag.retrieval import retrieve_chunks
        chunks = retrieve_chunks(query, top_k=top_k, filter_doc_id=doc_id)
        for chunk in chunks:
            chunk["score"] = round(1 - chunk.pop("distance", 0), 4)
        return {"chunks": chunks}
    except Exception:
        return {"chunks": _lexical_search(query, top_k, doc_id)}


def _profile(employee_id: str) -> dict[str, Any]:
    employee = _employee(employee_id)
    if employee is None:
        return {"employee_id": employee_id, "found": False}
    return {key: employee.get(key) for key in (
        "employee_id", "name", "role", "department", "office_location", "remote_status",
        "hire_date", "manager_id", "years_of_service") } | {"found": True}


def _pto(employee_id: str) -> dict[str, Any]:
    employee = _employee(employee_id)
    if employee is None:
        return {"employee_id": employee_id, "found": False}
    pending = [{"start_date": item["start_date"], "end_date": item["end_date"],
                "days": item["days_requested"], "status": item["status"]}
               for item in employee.get("pending_pto_requests", [])]
    return {"employee_id": employee_id, "pto_balance_days": employee["pto_balance_days"],
            "pending_pto_requests": pending, "found": True}


def _compliance(employee_id: str, action: str, context: str = "") -> dict[str, Any]:
    profile = _employee(employee_id)
    if profile is None:
        return {"compliant": False, "verdict": "Employee record was not found.", "citations": [], "conditions": ""}
    action_lower = action.lower()
    chunks = _search(f"{action} {context}", top_k=4)["chunks"]
    citations = [f"{chunk['doc_id']} § {chunk['section']}" for chunk in chunks]
    if any(word in action_lower for word in ("spain", "abroad", "international", "another state", "remote work")):
        return {"compliant": False, "verdict": "Requires HR, Legal, and manager review before working from another jurisdiction.",
                "citations": citations, "conditions": "Do not begin the arrangement until written approval is received."}
    amount = re.search(r"\$([\d,]+)", action)
    if amount and float(amount.group(1).replace(",", "")) > 500:
        return {"compliant": True, "verdict": "Potentially reimbursable, but pre-approval is required for this amount.",
                "citations": citations, "conditions": "Written manager and Finance approval is required before the expense."}
    return {"compliant": True, "verdict": "No automatic policy conflict was identified; verify the cited conditions before proceeding.",
            "citations": citations, "conditions": "Keep required receipts and obtain any approvals stated in policy."}


@app.get("/tools")
def discover_tools() -> dict[str, Any]:
    return {"tools": _tools()}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "tool_count": len(_tools())}


@app.post("/tools/{tool_name}")
def call_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "search_policy_documents":
        return _search(args["query"], int(args.get("top_k", 5)), args.get("doc_id"))
    if tool_name == "get_policy_section":
        chunks = _search(args["section"], 10, args["doc_id"])["chunks"]
        match = next((chunk for chunk in chunks if args["section"].lower() in chunk["section"].lower()), None)
        return match | {"found": True} if match else {"doc_id": args["doc_id"], "section": args["section"], "found": False}
    if tool_name == "lookup_employee_profile":
        return _profile(args["employee_id"])
    if tool_name == "check_pto_balance":
        return _pto(args["employee_id"])
    if tool_name == "lookup_benefits_status":
        employee = _employee(args["employee_id"])
        return {"employee_id": args["employee_id"], "benefits_election": employee.get("benefits_election", {}), "found": employee is not None}
    if tool_name == "check_policy_compliance":
        return _compliance(args["employee_id"], args["action"], args.get("context", ""))
    if tool_name == "create_mock_hr_ticket":
        return {"ticket_id": f"HR-{uuid4().hex[:8].upper()}", "status": "created",
                "created_at": datetime.now(UTC).isoformat(), "assigned_to": "People Operations"}
    if tool_name == "draft_hr_email":
        return {"status": "drafted", "draft": {key: args[key] for key in ("recipient_role", "subject", "body")}}
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
