"""Acme Corp HR tool server.

Exposes all 8 HR tools in two ways:
  1. As importable Python functions (used by expense_advisor and tests).
  2. As an MCP Streamable HTTP service (used by the agent orchestrator).
     POST /mcp          — MCP initialize, tools/list, tools/call
     Legacy REST routes remain for diagnostics and older smoke tests.
     GET  /tools           — schema discovery
     POST /tools/{name}    — tool invocation
     GET  /health          — liveness check

Run:
    python -m src.mcp.server          # starts REST server on port 8001
"""

from __future__ import annotations

import json
import re
import uuid
from functools import lru_cache
from datetime import UTC, datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from mcp.server.mcpserver import MCPServer

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT           = Path(__file__).parents[2]
_EMPLOYEES_FILE = _ROOT / "data" / "employees.json"
_SCHEMA_FILE    = _ROOT / "project_plan" / "mcp_tools_schema.json"
_POLICIES_DIR   = _ROOT / "data" / "policies"
PORT = 8001

# Keywords that trigger a non-compliant verdict when semantically close to the query
_PROHIBITIONS = {
    "prohibited", "not permitted", "not allowed", "must not",
    "may not", "forbidden", "shall not", "strictly prohibited",
}

# ── Employee data (lazy singleton) ────────────────────────────────────────────
_employees_by_id: dict[str, dict] | None = None


def _get_employees() -> dict[str, dict]:
    global _employees_by_id
    if _employees_by_id is None:
        raw = json.loads(_EMPLOYEES_FILE.read_text(encoding="utf-8"))
        _employees_by_id = {e["employee_id"]: e for e in raw["employees"]}
    return _employees_by_id


# ── Ticket store (in-memory + file-backed) ───────────────────────────────────
_TICKETS_FILE = _ROOT / "data" / "tickets.jsonl"
_tickets: dict[str, dict] = {}


def _load_tickets() -> None:
    if not _TICKETS_FILE.exists():
        return
    for line in _TICKETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                t = json.loads(line)
                _tickets[t["ticket_id"]] = t
            except (json.JSONDecodeError, KeyError):
                pass


def _persist_ticket(ticket: dict) -> None:
    try:
        _TICKETS_FILE.parent.mkdir(exist_ok=True)
        with _TICKETS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    except Exception:
        pass


_load_tickets()

# ── Internal search helpers ───────────────────────────────────────────────────

@lru_cache(maxsize=32)
def _policy_lines(path_string: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Lightweight, format-aware fallback when the vector index is unavailable."""
    path = Path(path_string)
    lines: list[tuple[str, str]] = []
    title = path.stem.replace("_", " ").title()
    section = title
    if path.suffix == ".html":
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for element in soup.find_all(["h1", "h2", "h3", "p", "li", "tr"]):
            content = element.get_text(" ", strip=True)
            if not content:
                continue
            if element.name in ("h1", "h2", "h3"):
                section = content
                if element.name == "h1":
                    title = content
            lines.append((section, content))
    else:
        if path.suffix == ".pdf":
            from pypdf import PdfReader

            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        else:
            text = path.read_text(encoding="utf-8")
        for raw in text.splitlines():
            content = raw.strip()
            if not content:
                continue
            heading = re.match(r"^(?:#{1,3}\s*)?(\d+(?:\.\d+)*\.?)\s+([A-Z][^|]{2,90})$", content)
            if content.startswith("#"):
                section = content.lstrip("#").strip()
                if content.startswith("# "):
                    title = section
            elif heading:
                section = f"{heading.group(1)} {heading.group(2)}"
            lines.append((section, content))
    combined = "\n".join(content for _, content in lines[:20])
    doc_id_match = re.search(r"POL-[A-Z]+-\d+", combined)
    doc_id = doc_id_match.group(0) if doc_id_match else path.stem.upper()
    return doc_id, title, lines


def _lexical_search(query: str, top_k: int, doc_id: str | None = None) -> list[dict[str, Any]]:
    """Deterministic keyword fallback used when the Chroma index is unavailable."""
    terms = {t.lower() for t in re.findall(r"[a-zA-Z]{3,}", query)}
    matches: list[dict[str, Any]] = []
    for policy in sorted(_POLICIES_DIR.iterdir()):
        if policy.suffix not in (".md", ".html", ".txt", ".pdf"):
            continue
        pid, title, lines = _policy_lines(str(policy))
        if doc_id and pid != doc_id:
            continue
        for i, (section, line) in enumerate(lines):
            score = sum(t in line.lower() or t in section.lower() for t in terms)
            if score:
                window = " ".join(text for _, text in lines[max(0, i - 1):i + 3]).strip()
                dist   = max(0.0, 1.0 - score / max(len(terms), 1))
                matches.append({"doc_id": pid, "doc_title": title, "section": section,
                                 "text": window, "snippet": window[:180],
                                 "score": round(1.0 - dist, 4), "distance": dist})
    return sorted(matches, key=lambda x: x["score"], reverse=True)[:top_k]


def _prefer_exact_section_matches(chunks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Promote policy sections named explicitly in the employee's question.

    Semantic retrieval remains the primary ranking; this only breaks close ties
    in favour of an exact multi-word section phrase such as ``sick leave``.
    """
    words = re.findall(r"[a-zA-Z]{3,}", query.lower())
    phrases = {" ".join(words[index:index + 2]) for index in range(len(words) - 1)}

    def exact_matches(chunk: dict[str, Any]) -> int:
        section = chunk.get("section", "").lower()
        return sum(phrase in section for phrase in phrases)

    return sorted(
        chunks,
        key=lambda chunk: (exact_matches(chunk), chunk.get("score", 0)),
        reverse=True,
    )


def _retrieve(query: str, top_k: int = 5, doc_id: str | None = None) -> list[dict[str, Any]]:
    """Return chunks with both 'distance' and 'score' present, falling back to lexical search."""
    try:
        from src.rag.retrieval import retrieve_chunks
        chunks = retrieve_chunks(query, top_k=top_k, filter_doc_id=doc_id)
        for c in chunks:
            c.setdefault("score", round(1.0 - c.get("distance", 0), 4))
            c.setdefault("snippet", c["text"][:180])
        return _prefer_exact_section_matches(chunks, query)
    except Exception:
        return _prefer_exact_section_matches(_lexical_search(query, top_k, doc_id), query)


# ── Tool 1: search_policy_documents ───────────────────────────────────────────

def search_policy_documents(
    query: str,
    top_k: int = 5,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Semantic search across all HR policy documents. Returns ranked chunks with source citations."""
    chunks = _retrieve(query, top_k=top_k, doc_id=doc_id)
    # The remote-work workflow asks about location eligibility first. Security
    # passages remain available, but should not displace the governing policy
    # as the lead citation when lexical fallback is used without Chroma.
    if "policy focus: remote-work eligibility" in query.lower() and not doc_id:
        if not any(c["doc_id"] == "POL-RW-001" for c in chunks):
            governing = _retrieve(query, top_k=1, doc_id="POL-RW-001")
            chunks = (governing + chunks)[:top_k]
        chunks = sorted(chunks, key=lambda c: (c["doc_id"] == "POL-RW-001", c.get("score", 0)), reverse=True)
    return {
        "chunks": [
            {
                "doc_id":    c["doc_id"],
                "doc_title": c["doc_title"],
                "section":   c["section"],
                "text":      c["text"],
                "snippet":   c.get("snippet", c["text"][:180]),
                "score":     c.get("score", round(1.0 - c.get("distance", 0), 4)),
            }
            for c in chunks
        ]
    }


# ── Tool 2: get_policy_section ────────────────────────────────────────────────

def get_policy_section(doc_id: str, section: str) -> dict[str, Any]:
    """Retrieve the closest-matching section from a specific policy document."""
    # Search the full document before choosing a result.  A semantic nearest
    # neighbour alone can select a related section (for example, a general
    # business-meals rule instead of the specifically named travel-meals rule).
    chunks = _retrieve(section, top_k=100, doc_id=doc_id)
    if not chunks:
        return {"doc_id": doc_id, "doc_title": "", "section": section, "text": "", "found": False}
    needle = " ".join(section.lower().split())
    matches = [chunk for chunk in chunks if needle in " ".join(chunk["section"].lower().split())]
    best = matches[0] if matches else chunks[0]
    section_chunks = [chunk for chunk in matches if chunk["section"] == best["section"]]
    section_text = "\n".join(dict.fromkeys(chunk["text"] for chunk in section_chunks or [best]))[:8_000]
    return {
        "doc_id":    best["doc_id"],
        "doc_title": best["doc_title"],
        "section":   best["section"],
        "text":      section_text,
        "found":     True,
    }


# ── Tool 3: lookup_employee_profile ───────────────────────────────────────────

def lookup_employee_profile(employee_id: str) -> dict[str, Any]:
    """Return the full HR profile for an employee by ID (e.g. 'EMP-001').

    Includes PTO balance, pending requests, and benefits election so callers
    can get all employee context in a single tool call.
    """
    emp = _get_employees().get(employee_id)
    if not emp:
        return {"employee_id": employee_id, "found": False}
    b = emp.get("benefits_election", {})
    return {
        "employee_id":      emp["employee_id"],
        "name":             emp["name"],
        "role":             emp["role"],
        "department":       emp["department"],
        "office_location":  emp["office_location"],
        "remote_status":    emp["remote_status"],
        "hire_date":        emp["hire_date"],
        "manager_id":       emp.get("manager_id"),
        "years_of_service": emp["years_of_service"],
        "pto_balance_days": emp["pto_balance_days"],
        "pending_pto_requests": [
            {"start_date": r["start_date"], "end_date": r["end_date"],
             "days": r["days_requested"], "status": r["status"]}
            for r in emp.get("pending_pto_requests", [])
        ],
        "benefits_election": {
            "health_plan":             b.get("health_plan", ""),
            "dental":                  b.get("dental", False),
            "vision":                  b.get("vision", False),
            "fsa_enrolled":            b.get("fsa_enrolled", False),
            "hsa_enrolled":            b.get("hsa_enrolled", False),
            "401k_contribution_pct":   b.get("401k_contribution_pct", 0),
            "401k_employer_match_pct": b.get("401k_employer_match_pct", 0),
            "life_insurance":          b.get("life_insurance", ""),
            "commuter_benefit":        b.get("commuter_benefit", False),
        },
        "found": True,
    }


# ── Tool 4: check_pto_balance ─────────────────────────────────────────────────

def check_pto_balance(employee_id: str) -> dict[str, Any]:
    """Return an employee's current PTO balance and any pending PTO requests."""
    emp = _get_employees().get(employee_id)
    if not emp:
        return {"employee_id": employee_id, "found": False}
    return {
        "employee_id":      emp["employee_id"],
        "pto_balance_days": emp["pto_balance_days"],
        "pending_pto_requests": [
            {"start_date": r["start_date"], "end_date": r["end_date"],
             "days": r["days_requested"], "status": r["status"]}
            for r in emp.get("pending_pto_requests", [])
        ],
        "found": True,
    }


# ── Tool 5: lookup_benefits_status ────────────────────────────────────────────

def lookup_benefits_status(employee_id: str) -> dict[str, Any]:
    """Return an employee's current benefits elections (health, dental, vision, FSA/HSA, 401k)."""
    emp = _get_employees().get(employee_id)
    if not emp:
        return {"employee_id": employee_id, "found": False}
    b = emp.get("benefits_election", {})
    return {
        "employee_id": emp["employee_id"],
        "benefits_election": {
            "health_plan":             b.get("health_plan", ""),
            "dental":                  b.get("dental", False),
            "vision":                  b.get("vision", False),
            "fsa_enrolled":            b.get("fsa_enrolled", False),
            "hsa_enrolled":            b.get("hsa_enrolled", False),
            "401k_contribution_pct":   b.get("401k_contribution_pct", 0),
            "401k_employer_match_pct": b.get("401k_employer_match_pct", 0),
            "life_insurance":          b.get("life_insurance", ""),
            "commuter_benefit":        b.get("commuter_benefit", False),
        },
        "found": True,
    }


# ── Tool 6: create_mock_hr_ticket ─────────────────────────────────────────────

_ASSIGNEE = {
    "pto_request":           "pto-team@acmecorp.com",
    "benefits_change":       "benefits@acmecorp.com",
    "policy_question":       "people-ops@acmecorp.com",
    "accommodation_request": "accessibility@acmecorp.com",
    "general_inquiry":       "people-ops@acmecorp.com",
}


def create_mock_hr_ticket(
    employee_id: str,
    ticket_type: str,
    subject: str,
    description: str,
    requested_start_date: str | None = None,
    requested_end_date: str | None = None,
) -> dict[str, Any]:
    """Create a mock HR service ticket. Requires explicit user confirmation before calling."""
    ticket_id   = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    now         = datetime.now(UTC).isoformat()
    assigned_to = _ASSIGNEE.get(ticket_type, "people-ops@acmecorp.com")
    ticket = {
        "ticket_id": ticket_id, "employee_id": employee_id,
        "ticket_type": ticket_type, "subject": subject, "description": description,
        "requested_start_date": requested_start_date, "requested_end_date": requested_end_date,
        "status": "created", "created_at": now, "assigned_to": assigned_to,
    }
    _tickets[ticket_id] = ticket
    _persist_ticket(ticket)
    return {"ticket_id": ticket_id, "status": "created", "created_at": now, "assigned_to": assigned_to}


# ── Tool 7: check_policy_compliance ───────────────────────────────────────────

def check_policy_compliance(
    employee_id: str,
    action: str,
    context: str = "",
) -> dict[str, Any]:
    """Retrieve relevant policy and return a compliance assessment with citations."""
    emp = _get_employees().get(employee_id)
    emp_details = (
        f" Employee: role={emp['role']}, remote_status={emp['remote_status']}, "
        f"years_of_service={emp['years_of_service']}."
        if emp else ""
    )
    chunks = _retrieve(f"{action}. {context}.{emp_details}".strip(". "), top_k=5)

    if not chunks:
        return {"compliant": False, "verdict": "No relevant policy found. Consult People Operations.",
                "citations": [], "conditions": ""}

    citations  = [f"[{c['doc_id']} § {c['section']}]" for c in chunks]
    source_ids = ", ".join(dict.fromkeys(c["doc_id"] for c in chunks))
    top_text   = chunks[0]["text"].lower()
    best_dist  = chunks[0].get("distance", 1.0)
    conditions = "; ".join(dict.fromkeys(c["section"] for c in chunks[:3]))

    if best_dist < 0.30 and any(kw in top_text for kw in _PROHIBITIONS):
        return {
            "compliant":  False,
            "verdict":    (f"Policy context from {source_ids} contains explicit restrictions "
                           f"relevant to this action. Review the cited sections or consult "
                           f"People Operations before proceeding."),
            "citations":  citations,
            "conditions": conditions,
        }
    return {
        "compliant":  True,
        "verdict":    (f"No explicit prohibitions found in {source_ids} for this action. "
                       f"Verify the conditions in the cited sections apply to your situation."),
        "citations":  citations,
        "conditions": conditions,
    }


# ── Tool 8: draft_hr_email ────────────────────────────────────────────────────

_EMAIL_TO = {
    "pto_request":           "manager",
    "remote_work_request":   "manager",
    "expense_approval":      "people-ops@acmecorp.com",
    "accommodation_request": "accessibility@acmecorp.com",
    "general":               "people-ops@acmecorp.com",
}
_EMAIL_SUBJECTS = {
    "pto_request":           "PTO Request",
    "remote_work_request":   "Remote Work Approval Request",
    "expense_approval":      "Expense Reimbursement Request",
    "accommodation_request": "Workplace Accommodation Request",
    "general":               "HR Inquiry",
}
_EMAIL_INTROS = {
    "pto_request":           "I am writing to formally request time off from work. Please find the details of my request below.",
    "remote_work_request":   "I am writing to request approval for a remote work arrangement. Please find the details below.",
    "expense_approval":      "I am submitting a request for expense reimbursement. Please find the details of the expenditure below.",
    "accommodation_request": "I am writing to request a workplace accommodation. Please find the details of my request below.",
    "general":               "I am writing to the People Operations team with the following inquiry.",
}


def _name_to_email(name: str) -> str:
    parts = name.lower().split()
    return f"{parts[0][0]}.{parts[-1]}@acmecorp.com"


def draft_hr_email(
    employee_id: str,
    email_type: str,
    details: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Draft a professional HR email. Always returns a DRAFT — never sends.

    email_type values: pto_request, remote_work_request, expense_approval,
    accommodation_request, general.
    """
    employees    = _get_employees()
    emp          = employees.get(employee_id)
    sender_name  = emp["name"]       if emp else f"Employee {employee_id}"
    sender_role  = emp["role"]       if emp else "Unknown Role"
    sender_dept  = emp["department"] if emp else "Unknown Department"
    manager      = employees.get(emp["manager_id"]) if emp and emp.get("manager_id") else None
    manager_name = manager["name"] if manager else "People Operations Team"

    to_target = _EMAIL_TO.get(email_type, "people-ops@acmecorp.com")
    if to_target == "manager":
        to_addr    = _name_to_email(manager_name) if manager else "people-ops@acmecorp.com"
        salutation = f"Hi {manager_name.split()[0]},"
    else:
        to_addr    = to_target
        salutation = "Dear People Operations Team,"

    date_clause = ""
    if start_date and end_date and start_date != end_date:
        date_clause = f" from {start_date} to {end_date}"
    elif start_date:
        date_clause = f" on {start_date}"

    subject = _EMAIL_SUBJECTS.get(email_type, "HR Inquiry") + date_clause
    intro   = _EMAIL_INTROS.get(email_type, _EMAIL_INTROS["general"])

    body = f"""{salutation}

{intro}

{details}

Please let me know if you require any additional information or documentation.

Thank you for your time and consideration.

Best regards,
{sender_name}
{sender_role}, {sender_dept}"""

    return {
        "draft_only": True,
        "to":         to_addr,
        "cc":         "people-ops@acmecorp.com",
        "subject":    subject,
        "body":       body,
        "from_name":  sender_name,
        "from_email": _name_to_email(sender_name) if emp else f"{employee_id.lower()}@acmecorp.com",
    }


# ── MCP Streamable HTTP service and diagnostic REST routes ────────────────────

mcp = MCPServer("Acme HR tools", version="1.0.0")
for _tool_function in (
    search_policy_documents, get_policy_section, lookup_employee_profile,
    check_pto_balance, lookup_benefits_status, create_mock_hr_ticket,
    check_policy_compliance, draft_hr_email,
):
    mcp.add_tool(_tool_function, structured_output=True)

_mcp_app = mcp.streamable_http_app(
    streamable_http_path="/", stateless_http=True, json_response=True,
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Acme HR MCP Tool Server", version="1.0.0", lifespan=_lifespan)
app.mount("/mcp", _mcp_app)


def _schema() -> list[dict[str, Any]]:
    return json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))["tools"]


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "tool_count": len(_schema())}


@app.get("/tools")
def discover_tools() -> dict[str, Any]:
    return {"tools": _schema()}


@app.post("/tools/{tool_name}")
def call_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "search_policy_documents":
        return search_policy_documents(args["query"], int(args.get("top_k", 5)), args.get("doc_id"))
    if tool_name == "get_policy_section":
        return get_policy_section(args["doc_id"], args["section"])
    if tool_name == "lookup_employee_profile":
        return lookup_employee_profile(args["employee_id"])
    if tool_name == "check_pto_balance":
        return check_pto_balance(args["employee_id"])
    if tool_name == "lookup_benefits_status":
        return lookup_benefits_status(args["employee_id"])
    if tool_name == "create_mock_hr_ticket":
        return create_mock_hr_ticket(
            args["employee_id"], args["ticket_type"], args["subject"], args["description"],
            args.get("requested_start_date"), args.get("requested_end_date"),
        )
    if tool_name == "check_policy_compliance":
        return check_policy_compliance(args["employee_id"], args["action"], args.get("context", ""))
    if tool_name == "draft_hr_email":
        return draft_hr_email(
            args["employee_id"], args["email_type"], args["details"],
            args.get("start_date"), args.get("end_date"),
        )
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Acme HR Tool Server on http://127.0.0.1:{PORT}")
    uvicorn.run("src.mcp.server:app", host="127.0.0.1", port=PORT, reload=False)
