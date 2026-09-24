"""
MCP tool smoke tests — calls tool functions directly (no HTTP server required).

Run:
    python scripts/test_mcp.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mcp.server import (
    check_policy_compliance,
    check_pto_balance,
    create_mock_hr_ticket,
    draft_hr_email,
    get_policy_section,
    lookup_benefits_status,
    lookup_employee_profile,
    search_policy_documents,
)

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"


def check(label: str, condition: bool, detail: str = "") -> bool:
    tag = PASS if condition else FAIL
    print(f"  [{tag}] {label}" + (f"  →  {detail}" if detail else ""))
    return condition


# ── 1. Employee data tools ────────────────────────────────────────────────────

def test_employee_tools() -> bool:
    print("\n=== 1. Employee Data Tools ===")
    results = []

    # lookup_employee_profile — found
    p = lookup_employee_profile("EMP-001")
    results.append(check("EMP-001 found", p["found"] is True))
    results.append(check("EMP-001 name correct", p["name"] == "Sarah Chen", p.get("name")))
    results.append(check("EMP-001 has required fields",
                         all(k in p for k in ["role", "department", "remote_status", "hire_date"])))

    # lookup_employee_profile — not found
    miss = lookup_employee_profile("EMP-999")
    results.append(check("EMP-999 not found returns found=False", miss["found"] is False))

    # check_pto_balance
    pto = check_pto_balance("EMP-002")
    results.append(check("EMP-002 PTO found", pto["found"] is True))
    results.append(check("EMP-002 PTO balance correct", pto["pto_balance_days"] == 8.0,
                         str(pto.get("pto_balance_days"))))
    results.append(check("EMP-002 has pending PTO request", len(pto["pending_pto_requests"]) == 1))

    # lookup_benefits_status
    ben = lookup_benefits_status("EMP-001")
    results.append(check("EMP-001 benefits found", ben["found"] is True))
    results.append(check("EMP-001 health_plan present",
                         ben["benefits_election"]["health_plan"] == "PPO Premium"))
    results.append(check("EMP-001 benefits has all fields",
                         all(k in ben["benefits_election"]
                             for k in ["dental", "vision", "fsa_enrolled", "401k_percent"])))

    return all(results)


# ── 2. Ticket creation tool ───────────────────────────────────────────────────

def test_ticket_tool() -> bool:
    print("\n=== 2. Ticket Creation Tool ===")
    results = []

    tkt = create_mock_hr_ticket(
        "EMP-001", "pto_request",
        "Holiday leave request", "Requesting 3 days off in December.",
        "2025-12-22", "2025-12-24",
    )
    results.append(check("ticket_id format", tkt["ticket_id"].startswith("TKT-"),
                         tkt.get("ticket_id")))
    results.append(check("status = created", tkt["status"] == "created"))
    results.append(check("assigned to pto-team", tkt["assigned_to"] == "pto-team@acmecorp.com"))
    results.append(check("created_at present", bool(tkt.get("created_at"))))

    # Different ticket type
    tkt2 = create_mock_hr_ticket("EMP-002", "benefits_change", "Update dental", "Add vision plan.")
    results.append(check("benefits_change assigned correctly",
                         tkt2["assigned_to"] == "benefits@acmecorp.com"))

    return all(results)


# ── 3. draft_hr_email ────────────────────────────────────────────────────────

def test_draft_hr_email() -> bool:
    print("\n=== 3. draft_hr_email ===")
    results = []

    # PTO request — routes to manager
    draft = draft_hr_email(
        "EMP-001", "pto_request",
        "I would like to request 5 days off for a family vacation.",
        "2025-12-22", "2025-12-26",
    )
    results.append(check("draft_only=True always", draft["draft_only"] is True))
    results.append(check("PTO request addressed to manager",
                         "okafor" in draft["to"],          # EMP-001's manager is David Okafor
                         draft.get("to")))
    results.append(check("subject includes dates",
                         "2025-12-22" in draft["subject"] or "PTO" in draft["subject"],
                         draft.get("subject")))
    results.append(check("body contains employee name", "Sarah Chen" in draft["body"]))
    results.append(check("body contains details",
                         "family vacation" in draft["body"]))
    results.append(check("cc is people-ops",
                         draft["cc"] == "people-ops@acmecorp.com"))

    # Remote work request
    draft2 = draft_hr_email(
        "EMP-002", "remote_work_request",
        "I would like to work remotely from Spain for 6 weeks.",
        "2025-11-01", "2025-12-13",
    )
    results.append(check("remote_work routes to manager", "@acmecorp.com" in draft2["to"]))
    results.append(check("subject contains Remote Work", "Remote Work" in draft2["subject"]))

    # Unknown employee — graceful fallback
    draft3 = draft_hr_email("EMP-999", "general", "I have a general question.")
    results.append(check("unknown employee: no crash", "draft_only" in draft3))
    results.append(check("unknown employee: to is people-ops",
                         draft3["to"] == "people-ops@acmecorp.com"))

    return all(results)


# ── 4. RAG-backed tools ───────────────────────────────────────────────────────

def test_rag_tools() -> bool:
    print("\n=== 4. RAG-Backed Tools ===")
    results = []

    # search_policy_documents — basic
    res = search_policy_documents("How many PTO days do I accrue per year?", top_k=3)
    chunks = res["chunks"]
    results.append(check("search returns 3 chunks", len(chunks) == 3))
    results.append(check("top result is PTO policy", chunks[0]["doc_id"] == "POL-PTO-002",
                         f"got {chunks[0]['doc_id']}"))
    results.append(check("score is between 0 and 1",
                         all(0 < c["score"] <= 1.0 for c in chunks)))

    # search_policy_documents — with doc_id filter
    res2 = search_policy_documents("reimbursement limit", top_k=5, doc_id="POL-EXP-001")
    results.append(check("filtered search all from POL-EXP-001",
                         all(c["doc_id"] == "POL-EXP-001" for c in res2["chunks"])))

    # get_policy_section
    sec = get_policy_section("POL-PTO-002", "PTO Accrual Rates")
    results.append(check("get_policy_section found=True", sec["found"] is True))
    results.append(check("get_policy_section doc_id matches", sec["doc_id"] == "POL-PTO-002"))
    results.append(check("get_policy_section text non-empty", bool(sec.get("text"))))

    # get_policy_section — unknown doc
    sec2 = get_policy_section("POL-FAKE-999", "anything")
    results.append(check("unknown doc_id returns found=False", sec2["found"] is False))

    # check_policy_compliance
    cmp = check_policy_compliance("EMP-001", "expense a $300 home office chair",
                                  "employee is fully remote")
    results.append(check("compliance returns bool", isinstance(cmp["compliant"], bool)))
    results.append(check("compliance has citations", len(cmp["citations"]) > 0))
    results.append(check("compliance has verdict text", bool(cmp.get("verdict"))))

    return all(results)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("MCP Tool Smoke Tests")
    print("=" * 60)

    results = [
        test_employee_tools(),
        test_ticket_tool(),
        test_draft_hr_email(),
        test_rag_tools(),
    ]

    print("\n" + "=" * 60)
    if all(results):
        print("RESULT: ALL MCP TOOL TESTS PASSED.")
        return 0
    else:
        print("RESULT: FAILED — see FAIL lines above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
