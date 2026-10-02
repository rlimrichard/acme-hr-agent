"""Inspectable orchestration for specialist and general HR policy workflows."""

from __future__ import annotations

import os
import asyncio
import json
import re
from calendar import month_abbr, month_name
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
from mcp.client import Client

from src.agent.reasoner import (
    build_routing_prompt,
    build_synthesis_prompt,
    classify_workflow,
    synthesize_policy_answer,
)


@dataclass
class AgentResponse:
    answer: str
    citations: list[dict[str, str]] = field(default_factory=list)
    snippets: list[dict[str, str]] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    escalated: bool = False
    escalation_message: str | None = None
    requires_confirmation: bool = False
    llm_reasoning: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class MCPClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001")).rstrip("/")

    def discover_tools(self) -> list[dict[str, Any]]:
        async def discover() -> list[dict[str, Any]]:
            async with Client(f"{self.base_url}/mcp/") as client:
                result = await client.list_tools()
                return [tool.model_dump(by_alias=True, exclude_none=True) for tool in result.tools]
        return asyncio.run(discover())

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        async def invoke() -> dict[str, Any]:
            async with Client(f"{self.base_url}/mcp/") as client:
                result = await client.call_tool(tool, args)
                if result.is_error:
                    raise RuntimeError(f"MCP tool {tool} failed: {result.content}")
                if result.structured_content is not None:
                    return result.structured_content
                for block in result.content:
                    if getattr(block, "type", None) == "text":
                        return json.loads(block.text)
                raise RuntimeError(f"MCP tool {tool} returned no structured result")
        try:
            return asyncio.run(invoke())
        except Exception as exc:
            raise RuntimeError(f"MCP call failed for {tool}") from exc


class HRAgent:
    """Routes specialist requests and grounds every other policy question in RAG."""

    def __init__(self, client: MCPClient | None = None, top_k: int = 5) -> None:
        self.client = client or MCPClient()
        self.top_k = top_k

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
    def _record_answer_prompt(
        response: AgentResponse,
        *,
        workflow: str,
        query: str,
        employee: dict[str, Any],
        chunks: list[dict[str, Any]],
        compliance: dict[str, Any],
        fallback: str,
    ) -> None:
        response.llm_reasoning["answer_generation"] = {
            "prompt_type": "grounded-policy-answer-v1",
            "prompt_preview": build_synthesis_prompt(
                workflow=workflow,
                query=query,
                employee=employee,
                chunks=chunks,
                compliance=compliance,
                fallback=fallback,
            ),
        }

    @staticmethod
    def _kind(query: str) -> str:
        lowered = query.lower()
        # A benefit offered by a vendor is an ethics/gifts question, even when
        # it uses words such as "vacation" or "travel" that otherwise belong
        # to the PTO or expense workflows.
        if "vendor" in lowered and any(word in lowered for word in (
            "gift", "vacation", "trip", "travel", "flight", "hotel", "ticket", "event",
        )):
            return "policy"
        if (HRAgent._is_pto_submission(query)
                or any(word in lowered for word in ("pto", "time off", "leave", "vacation", "days off", "day off", "take off"))
                or re.search(r"\b\d+\s+(?:days?|weeks?)\s+off\b", lowered)):
            return "pto"
        # Also cover natural phrasing such as "can I work for four months from
        # Thailand?".  The LLM router may be unavailable, so this fallback
        # needs to recognize a work arrangement followed by a location.
        if (
            any(word in lowered for word in ("remote", "work from", "abroad", "spain", "another state", "international"))
            or re.search(r"\bwork(?:ing)?\b[^?.!]{0,80}\bfrom\b", lowered)
        ):
            return "remote"
        if any(word in lowered for word in (
            "expense", "reimburse", "standing desk", "chair", "home office",
            "per diem", "meal", "travel", "flight", "hotel", "mileage",
        )):
            return "expense"
        # All other questions enter the read-only general policy workflow.  It
        # retrieves evidence before the LLM reasons over it, rather than being
        # rejected by a keyword gate.
        return "policy"

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

    @staticmethod
    def _is_pto_submission(query: str) -> bool:
        """A request to submit, not a question about policy or eligibility."""
        lowered = query.lower()
        return bool(re.search(
            r"\b(?:submit|file|send)\s+(?:a\s+|my\s+)?(?:pto|vacation|leave|time[ -]off)\s*request\b|"
            r"\b(?:i want to|i would like to|i'd like to)\s+request\s+(?:pto|vacation|leave|time[ -]off)\b|"
            r"\b(?:can|could|may)\s+i\s+request\b[^?.!]{0,80}\boff\b|"
            r"\b(?:please\s+)?request\b[^?.!]{0,80}\boff\b",
            lowered,
        ))

    @staticmethod
    def _requested_pto_date(query: str, today: date | None = None) -> str | None:
        """Extract a stated month/day; assume the next occurrence if no year is given."""
        months = {name.lower(): number for number, name in enumerate(month_name) if number}
        months.update({name.lower(): number for number, name in enumerate(month_abbr) if number})
        months["sept"] = 9
        match = re.search(
            r"\b(" + "|".join(sorted(months, key=len, reverse=True)) + r")\.?\s+"
            r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", query.lower(),
        )
        if not match:
            return None
        current = today or date.today()
        year = int(match.group(3)) if match.group(3) else current.year
        try:
            requested = date(year, months[match.group(1)], int(match.group(2)))
            if not match.group(3) and requested < current:
                requested = date(year + 1, requested.month, requested.day)
        except ValueError:
            return None
        return requested.isoformat()

    @staticmethod
    def _is_capability_question(query: str) -> bool:
        """Recognize general introductions without swallowing a specific HR question."""
        words = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
        if not words:
            return False
        words = re.sub(r"^(?:(?:hi|hello|hey|good morning|good afternoon)(?:\s+|$))+", "", words)
        words = re.sub(r"\s+please$", "", words)
        if not words:
            return True
        return bool(re.fullmatch(
            r"(?:"
            r"what can (?:you|this (?:app|assistant)) (?:do(?: for me)?|help(?: me)? with)|"
            r"what do you (?:do|help with)|"
            r"what does this (?:app|assistant) do|"
            r"how can (?:you|this (?:app|assistant)) help(?: me)?|"
            r"what are your capabilities|"
            r"what (?:topics|questions) can you help(?: me)? with|"
            r"(?:tell|show) me what you can do|tell me about yourself|"
            r"can you help me|"
            r"help"
            r")",
            words,
        ))

    @staticmethod
    def _help() -> AgentResponse:
        return AgentResponse(
            answer=(
                "I can help with PTO and leave, remote or international-work requests, "
                "expense reimbursement and per diem, and HR policy questions—such as benefits, "
                "workplace conduct, or vendor gifts. What would you like to know?"
            )
        )

    def answer(self, query: str, employee_id: str, confirmed: bool = False) -> AgentResponse:
        if self._is_capability_question(query):
            response = self._help()
            response.llm_reasoning = {
                "routing": {
                    "prompt_type": "deterministic-help-route-v1",
                    "selected_workflow": "help",
                    "route_source": "deterministic capability route",
                    "prompt_fields": ["employee question"],
                    "instruction": "Answer capability questions directly without policy retrieval.",
                    "response_format": "concise capability overview",
                    "prompt_preview": query,
                }
            }
            return response
        # Let the reasoning model classify first.  The local router is retained
        # only for availability and validation failures from the provider.
        llm_kind = classify_workflow(query)
        kind = llm_kind or self._kind(query)
        # A clear request to submit the employee's own PTO must not silently
        # become a read-only policy answer if the classifier mislabels it.
        pto_request_safeguard = self._is_pto_submission(query) and self._kind(query) == "pto" and kind != "pto"
        if pto_request_safeguard:
            kind = "pto"
        if kind == "pto":
            response = self._pto(query, employee_id, confirmed)
        elif kind == "remote":
            response = self._remote(query, employee_id, confirmed)
        elif kind == "expense":
            response = self._expense(query, employee_id)
        else:
            response = self._policy(query, employee_id)
        answer_generation = response.llm_reasoning.get("answer_generation", {})
        response.llm_reasoning = {
            "routing": {
                "prompt_type": "workflow-classification-v1",
                "model": os.getenv("OPENROUTER_MODEL", "qwen/qwen3.8-27b:free"),
                "selected_workflow": kind,
                "route_source": ("explicit PTO request safeguard" if pto_request_safeguard
                                 else "llm" if llm_kind else "deterministic fallback"),
                "prompt_fields": ["employee question"],
                "instruction": (
                    "Classify the employee question as PTO, remote work, expense, or general policy. "
                    "Vendor-provided benefits are general policy questions."
                ),
                "response_format": "One lowercase workflow label only.",
                "prompt_preview": build_routing_prompt(query),
            },
            "answer_generation": answer_generation,
        }
        return response

    def _pto(self, query: str, employee_id: str, confirmed: bool = False) -> AgentResponse:
        response = AgentResponse(answer="")
        profile = self._invoke(response, "lookup_employee_profile", employee_id=employee_id)
        balance = self._invoke(response, "check_pto_balance", employee_id=employee_id)
        policies = self._invoke(
            response,
            "search_policy_documents",
            query=(
                f"{query}\nPolicy focus: PTO approval, blackout periods, leave accrual, "
                "vacation, personal time, and sick leave."
            ),
            top_k=self.top_k,
        )
        compliance = self._invoke(response, "check_policy_compliance", employee_id=employee_id, action=query, context="PTO and leave request")
        self._sources(response, policies["chunks"])
        days = re.search(r"(\d+(?:\.\d+)?)\s*(day|week)s?\b", query.lower())
        requested = float(days.group(1)) * (5 if days.group(2) == "week" else 1) if days else None
        enough = requested is None or balance.get("pto_balance_days", 0) >= requested
        amount_text = f"Your current balance is {balance.get('pto_balance_days', 0)} days"
        if requested is not None:
            amount_text += f"; the request appears to require about {requested:g} days, so it is {'within' if enough else 'above'} that balance"

        submit_request = self._is_pto_submission(query)
        if self._should_draft_pto_email(query) and not submit_request:
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
        lowered = query.lower()
        if "sick" in lowered and any(word in lowered for word in ("vacation", "separate", "pto")):
            deterministic_answer = (
                "[OFFICIAL POLICY] No. Acme Corp uses one unified PTO bank: vacation, personal, "
                "and sick time all draw from the same balance. There is no separate sick-leave bucket. "
                "[POL-PTO-002 § 7.1 Use of PTO for Sick Leave] "
                f"{amount_text}."
            )
        else:
            deterministic_answer = (
                f"[OFFICIAL POLICY] {amount_text}. PTO requires direct-manager approval and may be limited "
                f"by team coverage or a designated blackout period. {compliance['verdict']}"
            )
        self._record_answer_prompt(
            response,
            workflow="PTO and leave",
            query=query,
            employee=profile,
            chunks=policies["chunks"],
            compliance=compliance,
            fallback=deterministic_answer,
        )
        response.answer = synthesize_policy_answer(
            workflow="PTO and leave",
            query=query,
            employee=profile,
            chunks=policies["chunks"],
            compliance=compliance,
            fallback=deterministic_answer,
        ) + email_block
        if submit_request and profile.get("found", False) and enough:
            requested_date = self._requested_pto_date(query)
            if confirmed:
                ticket = self._invoke(response, "create_mock_hr_ticket", employee_id=employee_id,
                                      ticket_type="pto_request", subject="PTO request", description=query,
                                      requested_start_date=requested_date, requested_end_date=requested_date)
                response.answer = f"Your PTO request {ticket['ticket_id']} is in your manager's review queue. You can track it under Requests."
            else:
                when = f" for {requested_date}" if requested_date else ""
                response.answer = f"I can send your time-off request{when} to your manager for review. Would you like me to submit it?"
                response.requires_confirmation = True
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
        policies = self._invoke(
            response,
            "search_policy_documents",
            query=(
                f"{query}\nPolicy focus: remote-work eligibility, work location, international "
                "arrangements, tax, data security, and approval requirements."
            ),
            top_k=self.top_k,
        )
        compliance = self._invoke(response, "check_policy_compliance", employee_id=employee_id, action=query,
                                  context=f"remote status: {profile.get('remote_status', 'unknown')}")
        self._sources(response, policies["chunks"])
        if confirmed:
            ticket = self._invoke(response, "create_mock_hr_ticket", employee_id=employee_id, ticket_type="general_inquiry",
                                  subject="Remote-work eligibility request", description=query)
            ticket_text = (
                f" Your HR review request has been created: {ticket['ticket_id']}. "
                "People Operations will review the overseas work arrangement."
            )
        else:
            ticket_text = ""
            response.requires_confirmation = True
        deterministic_answer = (
            "Working from another country for an extended period needs approval before you make arrangements. "
            "Your manager and People Operations will review the location, schedule, and security requirements."
        )
        if not confirmed:
            deterministic_answer += " Would you like me to create an HR review request?"
        self._record_answer_prompt(
            response,
            workflow="remote-work eligibility",
            query=query,
            employee=profile,
            chunks=policies["chunks"],
            compliance=compliance,
            fallback=deterministic_answer,
        )
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
        result = _expense_run(employee_id, query, tool_caller=self.client.call, top_k=self.top_k)

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
            llm_reasoning={"answer_generation": result.get("llm_reasoning", {})},
        )

    def _policy(self, query: str, employee_id: str) -> AgentResponse:
        """Answer a read-only HR policy question using retrieved evidence."""
        response = AgentResponse(answer="")
        profile = self._invoke(response, "lookup_employee_profile", employee_id=employee_id)
        policies = self._invoke(
            response,
            "search_policy_documents",
            query=f"{query}\nPolicy focus: applicable Acme Corp HR policy and employee conduct rules.",
            top_k=self.top_k,
        )
        compliance = self._invoke(
            response,
            "check_policy_compliance",
            employee_id=employee_id,
            action=query,
            context="general HR policy question",
        )
        chunks = policies.get("chunks", [])
        self._sources(response, chunks)
        evidence = "\n\n".join(
            f"[OFFICIAL POLICY] {chunk.get('text', '')} "
            f"[{chunk.get('doc_id', '')} § {chunk.get('section', '')}]"
            for chunk in chunks[:3]
            if chunk.get("text")
        )
        amount_match = re.search(
            r"(?:\$\s*([\d,]+(?:\.\d{1,2})?)|\b([\d,]+(?:\.\d{1,2})?)\s*dollars?\b)",
            query,
            re.IGNORECASE,
        )
        amount_text = next((group for group in amount_match.groups() if group), None) if amount_match else None
        amount = float(amount_text.replace(",", "")) if amount_text else None
        lowered = query.lower()
        vendor_benefit = "vendor" in lowered and any(word in lowered for word in (
            "gift", "vacation", "trip", "travel", "flight", "hotel", "ticket", "event",
        ))
        is_over_limit_gift = vendor_benefit and (
            (amount is not None and amount > 75)
            or any(word in lowered for word in ("vacation", "trip", "travel", "flight", "hotel"))
        )
        if is_over_limit_gift:
            item = f"A ${amount:,.0f} gift" if amount is not None else "A vendor-paid vacation or trip"
            fallback = (
                "[OFFICIAL POLICY] No. You may accept a vendor gift only when its value "
                "is $75 or less per source per year. %s exceeds that limit and must "
                "be declined; if it was physically received, share it with the team and disclose "
                "it to your manager. [POL-WPC-009 § 7.1 Receiving Gifts]\n\n%s"
            ) % (item, evidence)
            response.escalated = True
            response.escalation_message = "Do not accept this vendor gift without manager or Legal guidance."
        else:
            fallback = evidence or (
                "[OFFICIAL POLICY] No relevant policy text was retrieved. Please contact "
                "People Operations for guidance."
            )
        self._record_answer_prompt(
            response,
            workflow="general HR policy",
            query=query,
            employee=profile,
            chunks=chunks,
            compliance=compliance,
            fallback=fallback,
        )
        response.answer = synthesize_policy_answer(
            workflow="general HR policy",
            query=query,
            employee=profile,
            chunks=chunks,
            compliance=compliance,
            fallback=fallback,
        )
        if not profile.get("found", False):
            response.escalated = True
            response.escalation_message = "Your employee record could not be found. Please contact HR to verify your profile."
        elif not chunks:
            response.escalated = True
            response.escalation_message = "No relevant policy was found. Please contact People Operations for guidance."
        elif not compliance.get("compliant", True):
            response.escalated = True
            response.escalation_message = "This request needs HR, Legal, or manager review before you proceed."
        return response
