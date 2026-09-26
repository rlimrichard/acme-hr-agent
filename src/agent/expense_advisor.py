"""
Demo 3 — Expense Reimbursement Advisor Agent

Orchestrates a 4-step compliance check:
  1. lookup_employee_profile  — role, remote status
  2. search_policy_documents  — broad expense/equipment policy search
  3. get_policy_section       — specific limits from POL-EXP-001
  4. check_policy_compliance  — prohibition heuristic + citations
  + LLM synthesis             — grounded, cited final answer

Usage:
    python -m src.agent.expense_advisor "Can I expense a $1,200 standing desk?" EMP-001
"""

import os
import re
import time
from pathlib import Path
from typing import Any

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

from src.mcp.server import (
    check_policy_compliance,
    get_policy_section,
    lookup_employee_profile,
    search_policy_documents,
)

# ── Dollar-amount extractor ───────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"\$[\d,]+(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s*dollars?", re.I)


def _extract_amount(text: str) -> str:
    m = _AMOUNT_RE.search(text)
    return m.group(0) if m else ""


# ── LLM synthesis ─────────────────────────────────────────────────────────────

_SYNTHESIS_PROMPT = """\
You are an HR Policy Assistant for Acme Corp. Answer the employee's expense question
using ONLY the policy context provided. Be specific about dollar limits and conditions.

EMPLOYEE
  Name:          {name}
  Role:          {role}
  Remote status: {remote_status}

POLICY CONTEXT
{context_block}

COMPLIANCE PRE-ASSESSMENT
{compliance_verdict}

AVAILABLE CITATIONS
{citations}

RULES (follow strictly)
1. Prefix every policy fact with [OFFICIAL POLICY] and cite it as [DOC-ID § Section].
2. State the specific dollar limit if found in context.
3. List any conditions (remote-only, role-based, receipt requirements, etc.).
4. Suggest the clear next step (submit receipt, open ticket, contact manager).
5. If the context is insufficient, say so and refer to people-ops@acmecorp.com.
6. Never invent policy text not present above.

EMPLOYEE QUESTION: {query}"""


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_DEFAULT_MODEL = "anthropic/claude-haiku-4-5"


def _synthesize(
    query: str,
    employee: dict,
    chunks: list[dict],
    section: dict,
    compliance: dict,
) -> str:
    """Call an LLM via OpenRouter; fall back to a structured template if no key."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return _template_answer(query, employee, compliance)

    try:
        from openai import OpenAI
    except ImportError:
        return _template_answer(query, employee, compliance)

    # Build deduplicated context block
    seen: set[str] = set()
    parts: list[str] = []

    if section.get("found"):
        key = f"{section['doc_id']}:{section['section']}"
        if key not in seen:
            seen.add(key)
            parts.append(f"[{section['doc_id']} § {section['section']}]\n{section['text']}")

    for c in chunks:
        key = f"{c['doc_id']}:{c['section']}"
        if key not in seen:
            seen.add(key)
            parts.append(f"[{c['doc_id']} § {c['section']}]\n{c['text']}")

    prompt = _SYNTHESIS_PROMPT.format(
        name=employee.get("name", "Employee"),
        role=employee.get("role", "Unknown"),
        remote_status=employee.get("remote_status", "Unknown"),
        context_block="\n\n".join(parts) or "(No policy context retrieved.)",
        compliance_verdict=compliance.get("verdict", ""),
        citations="\n".join(compliance.get("citations", [])) or "(none)",
        query=query,
    )

    model = os.environ.get("OPENROUTER_MODEL", _OPENROUTER_DEFAULT_MODEL)
    client = OpenAI(api_key=api_key, base_url=_OPENROUTER_BASE_URL)
    response = client.chat.completions.create(
        model=model,
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _template_answer(query: str, employee: dict, compliance: dict) -> str:
    """Structured fallback when OPENROUTER_API_KEY is not set."""
    name    = employee.get("name", "Employee")
    verdict = compliance.get("verdict", "")
    cites   = compliance.get("citations", [])
    conds   = compliance.get("conditions", "")

    lines = [
        f"Hi {name},",
        "",
        f'Regarding: "{query}"',
        "",
        f"**Policy assessment:** {verdict}",
    ]
    if conds:
        lines += ["", "**Relevant policy excerpts:**", conds]
    if cites:
        lines += ["", "**Sources:"] + [f"  {c}" for c in cites]
    lines += [
        "",
        "For a definitive ruling contact People Operations: people-ops@acmecorp.com",
    ]
    return "\n".join(lines)


# ── Timed tool wrapper ────────────────────────────────────────────────────────

def _call(step: int, tool_name: str, fn, **kwargs) -> tuple[Any, dict]:
    t0     = time.perf_counter()
    result = fn(**kwargs)
    ms     = round((time.perf_counter() - t0) * 1000)
    entry  = {
        "step":        step,
        "tool":        tool_name,
        "input":       kwargs,
        "output":      result,
        "duration_ms": ms,
    }
    return result, entry


# ── Main workflow ─────────────────────────────────────────────────────────────

def run(employee_id: str, query: str) -> dict[str, Any]:
    """
    Run the Expense Reimbursement Advisor workflow.

    Returns a dict with keys:
        answer      — synthesized, cited response string
        citations   — deduplicated [DOC-ID § Section] list
        tool_trace  — ordered list of tool calls (step, tool, input, output, duration_ms)
        compliant   — bool from compliance heuristic (None if employee not found)
        employee    — employee profile dict
    """
    trace: list[dict] = []
    step = 0

    def tool(name, fn, **kwargs):
        nonlocal step
        step += 1
        result, entry = _call(step, name, fn, **kwargs)
        trace.append(entry)
        return result

    # ── Step 1 ────────────────────────────────────────────────────────────────
    employee = tool("lookup_employee_profile", lookup_employee_profile,
                    employee_id=employee_id)

    if not employee.get("found"):
        return {
            "answer":     f"Employee {employee_id} not found. Please verify the ID.",
            "citations":  [],
            "tool_trace": trace,
            "compliant":  None,
            "employee":   employee,
        }

    # ── Step 2 ────────────────────────────────────────────────────────────────
    # Enrich the search query with employee context so retrieval is role-aware
    amount = _extract_amount(query)
    enriched = (
        f"{query} expense reimbursement home office equipment allowance limit "
        f"role {employee['role']} {employee['remote_status']}"
        + (f" amount {amount}" if amount else "")
    )
    policy_result = tool("search_policy_documents", search_policy_documents,
                         query=enriched, top_k=5)
    chunks = policy_result.get("chunks", [])

    # ── Step 3 ────────────────────────────────────────────────────────────────
    # Pick section hint from query keywords
    q_lower = query.lower()
    if any(w in q_lower for w in ("desk", "chair", "monitor", "furniture", "home office")):
        section_hint = "Home Office Equipment"
    elif any(w in q_lower for w in ("travel", "flight", "hotel", "meal")):
        section_hint = "Travel Expenses"
    elif any(w in q_lower for w in ("phone", "internet", "software")):
        section_hint = "Technology and Subscriptions"
    else:
        section_hint = "Reimbursement Limits"

    section = tool("get_policy_section", get_policy_section,
                   doc_id="POL-EXP-001", section=section_hint)

    # ── Step 4 ────────────────────────────────────────────────────────────────
    context = (
        f"employee is {employee['remote_status']}, role: {employee['role']}"
        + (f", requested amount: {amount}" if amount else "")
    )
    compliance = tool("check_policy_compliance", check_policy_compliance,
                      employee_id=employee_id,
                      action=query,
                      context=context)

    # ── Step 5: synthesize ────────────────────────────────────────────────────
    answer = _synthesize(query, employee, chunks, section, compliance)

    # Collect citations — compliance first, then top RAG chunks
    seen_cites: set[str] = set()
    citations: list[str] = []
    for c in compliance.get("citations", []) + [f"[{ch['doc_id']} § {ch['section']}]" for ch in chunks[:3]]:
        if c not in seen_cites:
            seen_cites.add(c)
            citations.append(c)

    return {
        "answer":     answer,
        "citations":  citations,
        "tool_trace": trace,
        "compliant":  compliance.get("compliant"),
        "employee":   employee,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_result(result: dict) -> None:
    trace = result["tool_trace"]

    print("\n── Tool Trace " + "─" * 51)
    for e in trace:
        out = e["output"]
        if "chunks" in out:
            top = out["chunks"][0] if out["chunks"] else {}
            summary = f"{len(out['chunks'])} chunks  top={top.get('doc_id')}  score={top.get('score')}"
        elif "name" in out:
            summary = f"name={out['name']}  role={out.get('role')}  remote={out.get('remote_status')}"
        elif "text" in out:
            snippet = (out.get("text") or "")[:60].replace("\n", " ")
            summary = f"found={out.get('found')}  section={out.get('section','')[:40]}…  text={snippet!r}…"
        elif "compliant" in out:
            summary = f"compliant={out['compliant']}  citations={len(out.get('citations', []))}"
        else:
            summary = str(out)[:80]
        print(f"  {e['step']}. {e['tool']}  ({e['duration_ms']} ms)")
        print(f"     → {summary}")

    print("\n── Answer " + "─" * 55)
    print(result["answer"])

    print("\n── Citations " + "─" * 51)
    for c in result["citations"]:
        print(f"  {c}")

    print("\n── Compliance verdict " + "─" * 43)
    print(f"  compliant = {result['compliant']}")
    print()


if __name__ == "__main__":
    import sys

    query       = sys.argv[1] if len(sys.argv) > 1 else \
                  "Can I expense a $1,200 standing desk for my home office?"
    employee_id = sys.argv[2] if len(sys.argv) > 2 else "EMP-001"

    print("=" * 65)
    print("Demo 3 — Expense Reimbursement Advisor")
    print("=" * 65)
    print(f"Employee : {employee_id}")
    print(f"Query    : {query}")

    _print_result(run(employee_id, query))
