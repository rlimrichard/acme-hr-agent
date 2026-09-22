"""Deterministic, inspectable orchestration for the three selected HR workflows."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class AgentResponse:
    answer: str
    citations: list[dict[str, str]] = field(default_factory=list)
    snippets: list[dict[str, str]] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    escalated: bool = False
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
        if any(word in lowered for word in ("pto", "time off", "leave", "vacation")) or re.search(r"\b\d+\s+weeks?\s+off\b", lowered):
            return "pto"
        if any(word in lowered for word in ("remote", "work from", "abroad", "spain", "another state", "international")):
            return "remote"
        if any(word in lowered for word in ("expense", "reimburse", "standing desk", "chair", "home office")):
            return "expense"
        return None

    def answer(self, query: str, employee_id: str, confirmed: bool = False) -> AgentResponse:
        kind = self._kind(query)
        if kind is None:
            return AgentResponse("I can help with PTO and leave, remote-work eligibility, or expense reimbursement. Please clarify which of those you need.", escalated=True)
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
        days = re.search(r"(\d+(?:\.\d+)?)\s*(?:day|week)", query.lower())
        requested = float(days.group(1)) * (5 if "week" in query.lower() else 1) if days else None
        enough = requested is None or balance.get("pto_balance_days", 0) >= requested
        email = self._invoke(response, "draft_hr_email", employee_id=employee_id, recipient_role="direct manager",
                             subject="PTO request", body=f"Hello, I would like to request PTO: {query}. Please let me know whether coverage and timing permit approval.")
        amount_text = f"Your current balance is {balance.get('pto_balance_days', 0)} days"
        if requested is not None:
            amount_text += f"; the request appears to require about {requested:g} days, so it is {'within' if enough else 'above'} that balance"
        response.answer = (f"[OFFICIAL POLICY] {amount_text}. PTO requires direct-manager approval and may be limited by team coverage or a designated blackout period. "
                           f"{compliance['verdict']} A manager-email draft was prepared but not sent.")
        response.escalated = not profile.get("found", False) or not enough
        return response

    def _remote(self, query: str, employee_id: str, confirmed: bool) -> AgentResponse:
        response = AgentResponse(answer="")
        profile = self._invoke(response, "lookup_employee_profile", employee_id=employee_id)
        policies = self._invoke(response, "search_policy_documents", query="remote work international location tax data security approval", top_k=5)
        compliance = self._invoke(response, "check_policy_compliance", employee_id=employee_id, action=query,
                                  context=f"remote status: {profile.get('remote_status', 'unknown')}")
        self._sources(response, policies["chunks"])
        response.answer = (f"[OFFICIAL POLICY] {compliance['verdict']} {compliance['conditions']} "
                           "The cited remote-work and security policies should guide the review.")
        response.escalated = True
        if confirmed:
            ticket = self._invoke(response, "create_mock_hr_ticket", employee_id=employee_id, ticket_type="general_inquiry",
                                  subject="Remote-work eligibility request", description=query)
            response.answer += f" Your mock approval ticket {ticket['ticket_id']} has been created."
        else:
            response.requires_confirmation = True
            response.answer += " If you want a mock HR approval ticket created, explicitly confirm that action."
        return response

    def _expense(self, query: str, employee_id: str) -> AgentResponse:
        response = AgentResponse(answer="")
        profile = self._invoke(response, "lookup_employee_profile", employee_id=employee_id)
        policies = self._invoke(response, "search_policy_documents", query="expense reimbursement home office equipment approval limits", top_k=5)
        compliance = self._invoke(response, "check_policy_compliance", employee_id=employee_id, action=query,
                                  context=f"role: {profile.get('role', 'unknown')}; remote status: {profile.get('remote_status', 'unknown')}")
        self._sources(response, policies["chunks"])
        response.answer = f"[OFFICIAL POLICY] {compliance['verdict']} {compliance['conditions']} Review the cited expense and equipment-policy snippets before making a purchase."
        response.escalated = not compliance["compliant"]
        return response
