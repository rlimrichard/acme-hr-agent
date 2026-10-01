"""Grounded OpenRouter synthesis shared by the HR workflows."""

from __future__ import annotations

import os
from typing import Any


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
_VALID_WORKFLOWS = {"pto", "remote", "expense", "policy"}


def build_routing_prompt(query: str) -> str:
    """Build the exact routing prompt retained in the admin audit log."""
    return """Classify this Acme Corp employee question into exactly one label.
Reply with only the label, lowercase, and no punctuation.

pto = a request or question about the employee's own leave, PTO, or vacation.
remote = an employee's remote-work location or arrangement.
expense = reimbursement or company-paid business expenses.
policy = every other HR, conduct, benefits, security, vendor, gift, ethics, or policy question.

Important: a vacation, trip, travel, or other benefit offered by a vendor is policy, not pto or expense.

QUESTION:
""" + query


def classify_workflow(query: str) -> str | None:
    """Use the configured LLM to select a read-only workflow label.

    Returns ``None`` when the provider is unavailable or its reply is not one
    of the four allowed labels.  Callers must then use their deterministic
    fallback router rather than treating an ambiguous model reply as a route.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=_OPENROUTER_BASE_URL)
        response = client.chat.completions.create(
            model=os.getenv("OPENROUTER_MODEL", _DEFAULT_MODEL),
            max_tokens=8,
            temperature=0,
            messages=[{
                "role": "user",
                "content": build_routing_prompt(query),
            }],
        )
        label = (response.choices[0].message.content or "").strip().lower()
        return label if label in _VALID_WORKFLOWS else None
    except Exception:
        return None


def _policy_context(chunks: list[dict[str, Any]]) -> str:
    """Format only retrieved policy evidence for the model prompt."""
    seen: set[tuple[str, str]] = set()
    parts: list[str] = []
    for chunk in chunks:
        key = (str(chunk.get("doc_id", "")), str(chunk.get("section", "")))
        if key in seen:
            continue
        seen.add(key)
        text = chunk.get("text") or chunk.get("snippet") or ""
        if text:
            parts.append(f"[{key[0]} § {key[1]}]\n{text}")
    return "\n\n".join(parts) or "(No policy excerpts were retrieved.)"


def build_synthesis_prompt(
    *,
    workflow: str,
    query: str,
    employee: dict[str, Any],
    chunks: list[dict[str, Any]],
    compliance: dict[str, Any],
    fallback: str,
) -> str:
    """Build the evidence-grounded answer prompt for the admin audit log."""
    employee_context = {
        key: employee.get(key)
        for key in ("name", "role", "department", "remote_status", "pto_balance_days")
        if employee.get(key) is not None
    }
    return f"""You are the reasoning layer for Acme Corp's HR assistant.
Answer the employee's {workflow} question using only the evidence below.

Rules:
1. Do not invent policy, balances, approvals, dates, or actions.
2. Clearly distinguish a policy fact from a recommendation.
3. Cite each policy fact inline as [DOC-ID § Section].
4. Do not claim that an email was sent, a request was approved, or a ticket was
   created unless that outcome appears in the deterministic summary.
5. If the evidence is insufficient, say that HR or the employee's manager must
   review it.
6. Keep the answer concise and useful.

EMPLOYEE CONTEXT
{employee_context}

RETRIEVED POLICY EVIDENCE
{_policy_context(chunks)}

COMPLIANCE RESULT
{compliance.get('verdict', '')}
{compliance.get('conditions', '')}

DETERMINISTIC SUMMARY
{fallback}

EMPLOYEE QUESTION
{query}
"""


def synthesize_policy_answer(
    *,
    workflow: str,
    query: str,
    employee: dict[str, Any],
    chunks: list[dict[str, Any]],
    compliance: dict[str, Any],
    fallback: str,
) -> str:
    """Ask the configured LLM for a grounded explanation, with a safe fallback.

    The caller still owns workflow routing and any write action.  This function
    only turns already-retrieved evidence into a readable answer.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return fallback

    try:
        from openai import OpenAI
    except ImportError:
        return fallback

    prompt = build_synthesis_prompt(
        workflow=workflow,
        query=query,
        employee=employee,
        chunks=chunks,
        compliance=compliance,
        fallback=fallback,
    )

    try:
        client = OpenAI(api_key=api_key, base_url=_OPENROUTER_BASE_URL)
        response = client.chat.completions.create(
            model=os.getenv("OPENROUTER_MODEL", _DEFAULT_MODEL),
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.choices[0].message.content
        return answer.strip() if answer else fallback
    except Exception:
        return fallback
