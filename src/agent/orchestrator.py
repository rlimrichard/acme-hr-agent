"""Deterministic, inspectable orchestration for the three selected HR workflows."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.agent.reasoner import synthesize_policy_answer


@dataclass
class AgentResponse:
    answer: str
    citations: list[dict[str, str]] = field(default_factory=list)
    snippets: list[dict[str, str]] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    escalated: bool = False
    escalation_message: str | None = None
    requires_confirmation: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class MCPClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001")).rstrip("/")

    def discover_tools(self) -> list[dict[str, Any]]:
        return httpx.get(f"{self.base_url}/tools", timeout=10).raise_for_status().json()["tools"]

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(f"{self.base_url}/tools/{tool}", json=args, timeout=20)
        response.raise_for_status()
        return response.json()


class HRAgent:
    """Routes PTO, remote-work, and expense questions to explicit MCP workflows."""

    def __init__(self, client: MCPClient | None = None) -> None:
        self.client = client or MCPClient()

    def _invoke(self, response: AgentResponse, tool: str, **args: Any) -> dict[str, Any]:
        result = self.client.call(tool, args)
        response.tool_trace.append({"step": len(response.tool_trace) + 1, "tool": tool, "args": args, "result": result})
        return result

    @staticmethod
    def _sources(response: AgentResponse, chunks: list[dict[str, Any]]) -> None:
        seen: set[tuple[str, str]] = set()
        for chunk in chunks:
            key = (chunk["doc_id"], chunk["section"])
            if key not in seen:
                response.citations.append({"doc_id": chunk["doc_id"], "doc_title": chunk["doc_title"], "section": chunk["section"]})
                response.snippets.append({"doc_id": chunk["doc_id"], "section": chunk["section"], "text": chunk["snippet"]})
                seen.add(key)

    @staticmethod
    def _kind(query: str) -> str | None:
        lowered = query.lower()
        if any(word in lowered for word in ("pto", "time off", "leave", "vacation", "days off", "day off", "take off")) or re.search(r"\b\d+\s+(?:days?|weeks?)\s+off\b", lowered):
            return "pto"
        if any(word in lowered for word in ("remote", "work from", "abroad", "spain", "another state", "international")):
            return "remote"
        if any(word in lowered for word in (
            "expense", "reimburse", "standing desk", "chair", "home office",
            "per diem", "meal", "travel", "flight", "hotel", "mileage",
        )):
            return "expense"
        return None

    # A policy question must never generate a manager email merely because it
    # mentions PTO or leave.  Draft only when the employee explicitly asks to
    # draft or submit a request.
    _EMAIL_DRAFT_PATTERNS = (
        r"\b(?:draft|write|prepare)\s+(?:an?\s+)?(?:email|pto|leave|time[ -]off)\b",
        r"\b(?:submit|file|send)\s+(?:an?\s+)?(?:pto|leave|time[ -]off)?\s*request\b",
        r"\b(?:i(?: would|'d) like to|i want to)\s+(?:request|take)\b",
    )

    @classmethod
    def _should_draft_pto_email(cls, query: str) -> bool:
        lowered = query.lower()
        return any(re.search(p, lowered) for p in cls._EMAIL_DRAFT_PATTERNS)

    def answer(self, query: str, employee_id: str, confirmed: bool = False) -> AgentResponse:
        kind = self._kind(query)
        if kind is None:
            return AgentResponse(
                "I can help with PTO and leave, remote-work eligibility, or expense reimbursement. Please clarify which of those you need.",
                escalated=True,
                escalation_message="This request is outside the assistant's supported topics. Please contact HR for help.",
            )
        if kind == "pto":
            return self._pto(query, employee_id)
        if kind == "remote":
            return self._remote(query, employee_id, confirmed)
        return self._expense(query, employee_id)

    def _pto(self, query: str, employee_id: str) -> AgentResponse:
        response = AgentResponse(answer="")
        profile = self._invoke(response, "lookup_employee_profile", employee_id=employee_id)
        balance = self._invoke(response, "check_pto_balance", employee_id=employee_id)
        policies = self._invoke(response, "search_policy_documents", query="PTO approval process, blackout periods, and leave accrual", top_k=5)
        compliance = self._invoke(response, "check_policy_compliance", employee_id=employee_id, action=query, context="PTO and leave request")
        self._sources(response, policies["chunks"])
        days = re.search(r"(\d+(?:\.\d+)?)\s*(day|week)s?\b", query.lower())
        requested = float(days.group(1)) * (5 if days.group(2) == "week" else 1) if days else None
        enough = requested is None or balance.get("pto_balance_days", 0) >= requested
        amount_text = f"Your current balance is {balance.get('pto_balance_days', 0)} days"
        if requested is not None:
            amount_text += f"; the request appears to require about {requested:g} days, so it is {'within' if enough else 'above'} that balance"

        if self._should_draft_pto_email(query):
            email = self._invoke(response, "draft_hr_email", employee_id=employee_id,
                                 email_type="pto_request",
                                 details=f"I would like to request PTO: {query}. Please let me know whether coverage and timing permit approval.")
            email_block = (
                f"\n\n── Draft email (not sent) ──\n"
                f"To: {email.get('to', 'your manager')}\n"
                f"Cc: {email.get('cc', '')}\n"
                f"Subject: {email.get('subject', 'PTO Request')}\n\n"
                f"{email.get('body', '')}"
            )
        else:
            email_block = ""
        deterministic_answer = (
            f"[OFFICIAL POLICY] {amount_text}. PTO requires direct-manager approval and may be limited "
            f"by team coverage or a designated blackout period. {compliance['verdict']}"
        )
        response.answer = synthesize_policy_answer(
            workflow="PTO and leave",
            query=query,
            employee=profile,
            chunks=policies["chunks"],
            compliance=compliance,
            fallback=deterministic_answer,
        ) + email_block
        if not profile.get("found", False):
            response.escalated = True
            response.escalation_message = "Your employee record could not be found. Please contact HR to verify your profile."
        elif not enough:
            response.escalated = True
            response.escalation_message = "This request exceeds your available PTO balance. Please discuss options with your manager or HR."
        return response

    def _remote(self, query: str, employee_id: str, confirmed: bool) -> AgentResponse:
        response = AgentResponse(answer="")
        profile = self._invoke(response, "lookup_employee_profile", employee_id=employee_id)
        policies = self._invoke(response, "search_policy_documents", query="remote work international location tax data security approval", top_k=5)
        compliance = self._invoke(response, "check_policy_compliance", employee_id=employee_id, action=query,
                                  context=f"remote status: {profile.get('remote_status', 'unknown')}")
        self._sources(response, policies["chunks"])
        if confirmed:
            ticket = self._invoke(response, "create_mock_hr_ticket", employee_id=employee_id, ticket_type="general_inquiry",
                                  subject="Remote-work eligibility request", description=query)
            ticket_text = f" A mock HR approval ticket {ticket['ticket_id']} has been created."
        else:
            ticket_text = ""
            response.requires_confirmation = True
        deterministic_answer = (f"[OFFICIAL POLICY] {compliance['verdict']} {compliance['conditions']} "
                                f"The cited remote-work and security policies should guide the review.")
        response.answer = synthesize_policy_answer(
            workflow="remote-work eligibility",
            query=query,
            employee=profile,
            chunks=policies["chunks"],
            compliance=compliance,
            fallback=deterministic_answer,
        ) + ticket_text
        response.escalated = True
        response.escalation_message = "Remote-work requests require HR review and approval before arrangements are finalized."
        return response

    def _expense(self, query: str, employee_id: str) -> AgentResponse:
        from src.agent.expense_advisor import run as _expense_run
        result = _expense_run(employee_id, query)

        # Normalise tool_trace to orchestrator format (input/output → args/result)
        tool_trace = [
            {"step": e["step"], "tool": e["tool"],
             "args": e.get("input", {}), "result": e.get("output", {})}
            for e in result.get("tool_trace", [])
        ]

        # Parse "[DOC-ID § Section]" citation strings into dicts
        citations: list[dict[str, str]] = []
        snippets:  list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in result.get("citations", []):
            m = re.match(r"\[([^\s]+)\s*§\s*(.+?)\]", raw)
            if m and raw not in seen:
                seen.add(raw)
                citations.append({"doc_id": m.group(1), "doc_title": "", "section": m.group(2)})
                snippets.append({"doc_id": m.group(1), "section": m.group(2), "text": ""})

        return AgentResponse(
            answer=result["answer"],
            citations=citations,
            snippets=snippets,
            tool_trace=tool_trace,
            escalated=not result.get("compliant", True),
            escalation_message=(
                "This expense needs HR review before reimbursement."
                if not result.get("compliant", True) else None
            ),
        )
