"""
Acme Corp HR MCP Server — 7 tools via Streamable HTTP on localhost:8001.

Run:
    python -m src.mcp.server
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP

from src.rag.retrieval import retrieve_chunks

# ── Paths ────────────────────────────────────────────────────────────────────
_PROJECT_ROOT  = Path(__file__).parent.parent.parent
EMPLOYEES_FILE = _PROJECT_ROOT / "data" / "employees.json"
PORT           = 8001

# Keywords that indicate an explicit prohibition in policy text
_PROHIBITIONS = {
    "prohibited", "not permitted", "not allowed", "must not",
    "may not", "forbidden", "shall not", "strictly prohibited",
}

# ── Employee data (lazy singleton) ───────────────────────────────────────────
_employees_by_id: dict[str, dict] | None = None


def _get_employees() -> dict[str, dict]:
    global _employees_by_id
    if _employees_by_id is None:
        raw = json.loads(EMPLOYEES_FILE.read_text(encoding="utf-8"))
        _employees_by_id = {e["employee_id"]: e for e in raw["employees"]}
    return _employees_by_id


# ── In-memory ticket store ───────────────────────────────────────────────────
_tickets: dict[str, dict] = {}

# ── MCP server ───────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Acme Corp HR",
    instructions=(
        "HR policy assistant tools for Acme Corp. "
        "Search policies, look up employee data, and create service tickets."
    ),
)


# ── Tool 1: search_policy_documents ─────────────────────────────────────────

@mcp.tool()
def search_policy_documents(
    query: str,
    top_k: int = 5,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Semantic search across all HR policy documents. Returns ranked chunks with source citations."""
    chunks = retrieve_chunks(query, top_k=top_k, filter_doc_id=doc_id)
    return {
        "chunks": [
            {
                "doc_id":    c["doc_id"],
                "doc_title": c["doc_title"],
                "section":   c["section"],
                "text":      c["text"],
                "snippet":   c["snippet"],
                "score":     round(1.0 - c["distance"], 4),
            }
            for c in chunks
        ]
    }


# ── Tool 2: get_policy_section ───────────────────────────────────────────────

@mcp.tool()
def get_policy_section(doc_id: str, section: str) -> dict[str, Any]:
    """Retrieve the closest-matching section from a specific policy document by doc_id and section name."""
    chunks = retrieve_chunks(section, top_k=10, filter_doc_id=doc_id)
    if not chunks:
        return {"doc_id": doc_id, "doc_title": "", "section": section, "text": "", "found": False}
    best = chunks[0]
    return {
        "doc_id":    best["doc_id"],
        "doc_title": best["doc_title"],
        "section":   best["section"],
        "text":      best["text"],
        "found":     True,
    }


# ── Tool 3: lookup_employee_profile ─────────────────────────────────────────

@mcp.tool()
def lookup_employee_profile(employee_id: str) -> dict[str, Any]:
    """Return the full HR profile for an employee by ID (e.g. 'EMP-001')."""
    emp = _get_employees().get(employee_id)
    if not emp:
        return {"employee_id": employee_id, "found": False}
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
        "found":            True,
    }


# ── Tool 4: check_pto_balance ────────────────────────────────────────────────

@mcp.tool()
def check_pto_balance(employee_id: str) -> dict[str, Any]:
    """Return an employee's current PTO balance and any pending PTO requests."""
    emp = _get_employees().get(employee_id)
    if not emp:
        return {"employee_id": employee_id, "found": False}
    return {
        "employee_id":      emp["employee_id"],
        "pto_balance_days": emp["pto_balance_days"],
        "pending_pto_requests": [
            {
                "start_date": r["start_date"],
                "end_date":   r["end_date"],
                "days":       r["days_requested"],
                "status":     r["status"],
            }
            for r in emp.get("pending_pto_requests", [])
        ],
        "found": True,
    }


# ── Tool 5: lookup_benefits_status ───────────────────────────────────────────

@mcp.tool()
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
            "401k_percent":            b.get("401k_contribution_pct", 0),
            "401k_employer_match_pct": b.get("401k_employer_match_pct", 0),
            "life_insurance":          b.get("life_insurance", ""),
            "commuter_benefit":        b.get("commuter_benefit", False),
        },
        "found": True,
    }


# ── Tool 6: create_mock_hr_ticket ────────────────────────────────────────────

_ASSIGNEE = {
    "pto_request":           "pto-team@acmecorp.com",
    "benefits_change":       "benefits@acmecorp.com",
    "policy_question":       "people-ops@acmecorp.com",
    "accommodation_request": "accessibility@acmecorp.com",
    "general_inquiry":       "people-ops@acmecorp.com",
}


@mcp.tool()
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
    now         = datetime.now(timezone.utc).isoformat()
    assigned_to = _ASSIGNEE.get(ticket_type, "people-ops@acmecorp.com")

    _tickets[ticket_id] = {
        "ticket_id":            ticket_id,
        "employee_id":          employee_id,
        "ticket_type":          ticket_type,
        "subject":              subject,
        "description":          description,
        "requested_start_date": requested_start_date,
        "requested_end_date":   requested_end_date,
        "status":               "created",
        "created_at":           now,
        "assigned_to":          assigned_to,
    }

    return {
        "ticket_id":   ticket_id,
        "status":      "created",
        "created_at":  now,
        "assigned_to": assigned_to,
    }


# ── Tool 7: check_policy_compliance ──────────────────────────────────────────

@mcp.tool()
def check_policy_compliance(
    employee_id: str,
    action: str,
    context: str = "",
) -> dict[str, Any]:
    """Retrieve relevant policy and return a compliance assessment with citations for a proposed action."""
    emp = _get_employees().get(employee_id)
    emp_details = (
        f" Employee: role={emp['role']}, remote_status={emp['remote_status']}, "
        f"years_of_service={emp['years_of_service']}."
        if emp else ""
    )
    search_query = f"{action}. {context}.{emp_details}".strip(". ")

    chunks = retrieve_chunks(search_query, top_k=5)
    if not chunks:
        return {
            "compliant":  False,
            "verdict":    "No relevant policy found. Consult People Operations.",
            "citations":  [],
            "conditions": "",
        }

    citations  = [f"[{c['doc_id']} § {c['section']}]" for c in chunks]
    source_ids = ", ".join(dict.fromkeys(c["doc_id"] for c in chunks))

    # Prohibition check: only flag as non-compliant when the best match is
    # semantically close (distance < 0.30) AND contains prohibition language.
    top_text = chunks[0]["text"].lower()
    best_dist = chunks[0]["distance"]
    has_prohibition = best_dist < 0.30 and any(kw in top_text for kw in _PROHIBITIONS)

    conditions = "; ".join(c["snippet"][:100] for c in chunks[:2])

    if has_prohibition:
        return {
            "compliant":  False,
            "verdict":    (
                f"Policy context from {source_ids} contains explicit restrictions "
                f"relevant to this action. Review the cited sections or consult "
                f"People Operations before proceeding."
            ),
            "citations":  citations,
            "conditions": conditions,
        }

    return {
        "compliant":  True,
        "verdict":    (
            f"No explicit prohibitions found in {source_ids} for this action. "
            f"Verify the conditions in the cited sections apply to your situation."
        ),
        "citations":  citations,
        "conditions": conditions,
    }


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=PORT)
