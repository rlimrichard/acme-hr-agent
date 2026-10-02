import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

import src.agent.orchestrator as orchestrator
from src.app import main as app_main
from src.agent.orchestrator import HRAgent
from src.agent.reasoner import assess_answer_confidence, build_confidence_prompt
from src.mcp.server import _prefer_exact_section_matches, app
import src.mcp.server as mcp_server


class LocalMCPClient:
    """Test adapter that preserves the agent's tool-client interface."""

    def __init__(self) -> None:
        self.client = TestClient(app)

    def call(self, tool: str, args: dict) -> dict:
        response = self.client.post(f"/tools/{tool}", json=args)
        response.raise_for_status()
        return response.json()


def _agent() -> HRAgent:
    return HRAgent(LocalMCPClient())


def tool_names(response) -> list[str]:
    return [step["tool"] for step in response.tool_trace]


def _force_deterministic_routing(monkeypatch) -> None:
    """Keep workflow regression cases independent of provider availability."""
    monkeypatch.setattr(orchestrator, "classify_workflow", lambda _query: None)


# ── Tool discovery ─────────────────────────────────────────────────────────────

def test_discovers_eight_tools() -> None:
    response = TestClient(app).get("/tools")
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 8


def test_exact_section_phrase_is_preferred_over_close_semantic_match() -> None:
    chunks = [
        {"section": "Paid Time Off > PTO Usage", "score": 0.90},
        {"section": "Paid Time Off > Sick Leave", "score": 0.80},
    ]
    ranked = _prefer_exact_section_matches(chunks, "Is sick leave separate from vacation?")
    assert ranked[0]["section"].endswith("Sick Leave")


# ── _kind() routing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("Can I take some time off next week?",        "pto"),
    ("I need 2 weeks vacation in December",        "pto"),
    ("I'm requesting PTO for next Friday",         "pto"),
    ("can i request november 2nd off?",             "pto"),
    ("I want to work from Spain for a month",      "remote"),
    ("Can I work from home abroad?",               "remote"),
    ("Can I expense a $500 monitor?",              "expense"),
    ("I need to reimburse my standing desk",       "expense"),
    ("What is the office kitchen cleaning rota?",  "policy"),
    ("Can I receive a $1,000 gift from a vendor?", "policy"),
    ("Can I accept a Hawaiian vacation from a vendor?", "policy"),
])
def test_kind_routing(query: str, expected: str) -> None:
    assert HRAgent._kind(query) == expected


def test_november_2_request_asks_for_confirmation_then_creates_dated_manager_ticket(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "classify_workflow", lambda _query: None)
    query = "can i request november 2nd off?"
    assert HRAgent._requested_pto_date(query, today=date(2026, 10, 1)) == "2026-11-02"
    assert HRAgent._is_pto_submission(query) is True
    assert HRAgent._is_pto_submission("What is the PTO request policy?") is False

    class TicketInterceptClient(LocalMCPClient):
        def __init__(self):
            super().__init__()
            self.created = []

        def call(self, tool, args):
            if tool == "create_mock_hr_ticket":
                self.created.append(args)
                return {"ticket_id": "TKT-TEST-PTO", "status": "created"}
            return super().call(tool, args)

    client = TicketInterceptClient()
    agent = HRAgent(client)
    initial = agent.answer(query, "EMP-001")
    assert initial.requires_confirmation is True
    assert "manager" in initial.answer.lower()
    assert not client.created
    confirmed = agent.answer(query, "EMP-001", confirmed=True)
    assert confirmed.requires_confirmation is False
    assert "TKT-TEST-PTO" in confirmed.answer
    assert len(client.created) == 1
    assert client.created[0]["ticket_type"] == "pto_request"
    assert client.created[0]["requested_start_date"] == HRAgent._requested_pto_date(query)
    assert client.created[0]["requested_end_date"] == HRAgent._requested_pto_date(query)


def test_explicit_pto_request_is_not_lost_to_bad_llm_label(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "classify_workflow", lambda _query: "policy")
    response = _agent().answer("can i request november 2nd off?", "EMP-001")
    assert response.requires_confirmation is True
    assert response.llm_reasoning["routing"]["route_source"] == "explicit PTO request safeguard"
    assert "create_mock_hr_ticket" not in tool_names(response)


def test_llm_route_is_used_before_deterministic_fallback(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "classify_workflow", lambda _query: "policy")
    response = _agent().answer("Can I take a vacation next week?", "EMP-001")
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents", "check_policy_compliance",
    ]
    assert response.llm_reasoning["routing"]["route_source"] == "llm"
    assert "Classify" in response.llm_reasoning["routing"]["instruction"]
    assert "QUESTION:" in response.llm_reasoning["routing"]["prompt_preview"]
    assert "RETRIEVED POLICY EVIDENCE" in response.llm_reasoning["answer_generation"]["prompt_preview"]


# ── General policy workflow ───────────────────────────────────────────────────

def test_general_policy_query_retrieves_before_answering() -> None:
    response = _agent().answer("Can I receive a 1000 dollar gift from a vendor?", "EMP-001")
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents", "check_policy_compliance",
    ]
    assert response.citations
    assert "must be declined" in response.answer
    assert response.escalated is True


def test_vendor_paid_vacation_is_not_routed_to_pto() -> None:
    response = _agent().answer("Can I accept a Hawaiian vacation from a vendor?", "EMP-001")
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents", "check_policy_compliance",
    ]
    assert "must be declined" in response.answer
    assert response.escalated is True


# ── Response structure ────────────────────────────────────────────────────────

def test_response_as_dict_has_all_required_keys() -> None:
    d = _agent().answer("Can I take a day off?", "EMP-001").as_dict()
    for key in ("answer", "citations", "snippets", "tool_trace", "escalated", "requires_confirmation", "llm_reasoning"):
        assert key in d, f"missing key: {key}"


def test_confidence_scores_direct_help_but_does_not_invent_fallback_score() -> None:
    help_result = {"answer": "I can help with PTO.", "llm_reasoning": {"routing": {"selected_workflow": "help"}}}
    help_confidence = app_main._answer_confidence("What can you do?", help_result)
    assert help_confidence["score"] == 100
    assert help_confidence["method"] == "Deterministic capability intent and response"

    fallback_result = {"answer": "Policy answer", "llm_reasoning": {"routing": {
        "selected_workflow": "policy", "route_source": "deterministic fallback",
    }}}
    fallback_confidence = app_main._answer_confidence("Policy question", fallback_result)
    assert fallback_confidence["score"] is None
    assert fallback_confidence["status"] == "not_evaluated"


def test_confidence_review_uses_question_answer_and_retrieved_evidence(monkeypatch) -> None:
    import openai

    trace = [{"tool": "search_policy_documents", "result": {"chunks": [{
        "doc_id": "POL-RW-001", "section": "Eligibility", "text": "Manager approval is required.",
    }]}}]
    prompt = build_confidence_prompt("Can I work abroad?", "Ask your manager first.", trace)
    assert "Can I work abroad?" in prompt
    assert "Ask your manager first." in prompt
    assert "Manager approval is required." in prompt

    class FakeCompletion:
        def create(self, **kwargs):
            assert kwargs["messages"][0]["content"] == prompt
            return type("Reply", (), {"choices": [type("Choice", (), {
                "message": type("Message", (), {"content": '{"score": 84, "reason": "Relevant and supported."}'})()
            })()]})()

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletion()})()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-key")
    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    confidence = assess_answer_confidence("Can I work abroad?", "Ask your manager first.", trace)
    assert confidence["score"] == 84.0
    assert confidence["status"] == "scored"
    assert confidence["reason"] == "Relevant and supported."


def test_chat_audit_persists_confidence_without_exposing_it(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_main, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(app_main, "_answer_confidence", lambda _query, _result: {
        "score": 82.5, "method": "test similarity", "note": "not a correctness probability",
    })

    class FakeAgent:
        def __init__(self, _client):
            pass

        def answer(self, _query, _employee_id, _confirmed):
            return orchestrator.AgentResponse(answer="I can help with PTO.")

    monkeypatch.setattr(app_main, "HRAgent", FakeAgent)
    monkeypatch.setattr(app_main.portal, "USERS_FILE", tmp_path / "users.json")
    app_main.portal.USERS_FILE.write_text(json.dumps({"EMP-002": app_main.portal.password_hash("acme123")}), encoding="utf-8")
    client = TestClient(app_main.app)
    assert client.post("/login", data={"employee_id": "EMP-002", "password": "acme123"}).status_code == 200
    response = client.post("/chat", json={"query": "What can you do?", "employee_id": "EMP-002"})
    assert response.status_code == 200
    public = response.json()
    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8"))
    assert record["confidence"]["score"] == 82.5
    assert record["confirmed"] is False
    assert record["requires_confirmation"] is False
    assert record["created_ticket_ids"] == []
    assert "confidence" not in public


@pytest.mark.parametrize("query", [
    "What can you help with?",
    "Hi, what can you help me with?",
    "What does this assistant do?",
    "hi what can you do?",
    "What can you do for me?",
    "How can you help me?",
    "What topics can you help with?",
    "What are your capabilities?",
    "Tell me what you can do, please.",
    "Hello!",
])
def test_capability_questions_bypass_policy_retrieval(monkeypatch, query) -> None:
    def unexpected_classifier(_query):
        pytest.fail("Capability question should not call the LLM classifier")

    monkeypatch.setattr(orchestrator, "classify_workflow", unexpected_classifier)
    response = _agent().answer(query, "EMP-002")
    assert response.answer.startswith("I can help with PTO and leave")
    assert response.tool_trace == []
    assert response.citations == []
    assert response.escalated is False
    assert response.llm_reasoning["routing"]["selected_workflow"] == "help"


@pytest.mark.parametrize("query", [
    "What can you do about my PTO balance?",
    "Hi, can you help with sick leave?",
    "How can you help me expense a hotel?",
    "What can this assistant do about working from Thailand?",
])
def test_specific_hr_questions_are_not_capability_questions(query) -> None:
    assert HRAgent._is_capability_question(query) is False


# ── PTO workflow ──────────────────────────────────────────────────────────────

def test_pto_advisor_answers_information_request_without_drafting() -> None:
    response = _agent().answer("Can I take 3 weeks off in December?", "EMP-002")
    assert tool_names(response) == [
        "lookup_employee_profile", "check_pto_balance", "search_policy_documents",
        "check_policy_compliance",
    ]
    assert response.citations


def test_pto_escalated_when_balance_insufficient() -> None:
    # EMP-002 has 8.0 days balance; requesting 15 days should exceed it
    response = _agent().answer("I want to take 15 days off", "EMP-002")
    assert response.escalated is True


def test_pto_not_escalated_when_balance_sufficient() -> None:
    # EMP-004 has 22.0 days balance; 3 days is well within range
    response = _agent().answer("Can I take 3 days of vacation next month?", "EMP-004")
    assert response.escalated is False


def test_pto_answer_mentions_actual_balance() -> None:
    # EMP-001 has 14.5 days; the answer should state that number
    response = _agent().answer("How many PTO days can I take?", "EMP-001")
    assert "14.5" in response.answer


def test_pto_fallback_is_direct_without_compliance_boilerplate(monkeypatch) -> None:
    _force_deterministic_routing(monkeypatch)
    balance = _agent().answer("How much PTO time off do I have left?", "EMP-004")
    assert "22.0 days of PTO remaining" in balance.answer
    assert "No explicit prohibitions" not in balance.answer

    long_leave = _agent().answer("I want to take 3 weeks vacation in December.", "EMP-002")
    assert "15 workdays" in long_leave.answer
    assert "8.0 days" in long_leave.answer
    assert "No explicit prohibitions" not in long_leave.answer


def test_sick_leave_question_uses_unified_pto_policy() -> None:
    response = _agent().answer("Is sick leave separate from vacation?", "EMP-001")
    assert "unified PTO bank" in response.answer
    assert "separate sick-leave bucket" in response.answer


def test_pto_employee_not_found_escalates() -> None:
    response = _agent().answer("Can I take a day off?", "EMP-999")
    assert response.escalated is True


@pytest.mark.parametrize("query,employee_id,expected_escalated", [
    ("Can I take 2 days of vacation next month?", "EMP-004", False),
    ("Do I have enough PTO for a 10-day trip?", "EMP-001", False),
    ("Can I take 20 days off?", "EMP-003", True),
    ("How much vacation time do I have left?", "EMP-005", False),
    ("Can I use my PTO for a family event?", "EMP-002", False),
])
def test_deterministic_pto_cases(monkeypatch, query, employee_id, expected_escalated) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer(query, employee_id)
    assert tool_names(response) == [
        "lookup_employee_profile", "check_pto_balance", "search_policy_documents",
        "check_policy_compliance",
    ]
    assert response.citations
    assert response.escalated is expected_escalated


# ── Remote work workflow ──────────────────────────────────────────────────────

def test_remote_work_requires_confirmation_before_ticket() -> None:
    # Without confirmed=True, no ticket should be created and confirmation is requested
    response = _agent().answer("Can I work from Spain for 6 weeks?", "EMP-001")
    assert response.requires_confirmation is True
    assert "create_mock_hr_ticket" not in tool_names(response)
    assert "Spain" in response.answer
    assert "[POL-RW-001 § 2. Eligibility]" in response.answer


def test_remote_retrieval_leads_with_employee_question() -> None:
    query = "Can I work from Canada for two weeks?"
    response = _agent().answer(query, "EMP-001")
    search = next(step for step in response.tool_trace if step["tool"] == "search_policy_documents")
    assert search["args"]["query"].startswith(query)


def test_remote_work_ticket_created_when_confirmed(monkeypatch, tmp_path) -> None:
    # Exercise the real tool without writing a ticket into the deployed app.
    monkeypatch.setattr(mcp_server, "_TICKETS_FILE", tmp_path / "tickets.jsonl")
    monkeypatch.setattr(mcp_server, "_tickets", {})
    response = _agent().answer("Can I work from Spain for 6 weeks?", "EMP-001", confirmed=True)
    assert response.requires_confirmation is False
    assert "create_mock_hr_ticket" in tool_names(response)
    assert "Your HR review request has been created:" in response.answer
    assert "People Operations will review the requested work location." in response.answer
    assert len((tmp_path / "tickets.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_remote_work_always_escalated() -> None:
    response = _agent().answer("I want to work remotely from another country for 3 months", "EMP-003")
    assert response.escalated is True


@pytest.mark.parametrize("query,employee_id", [
    ("Can I work from Canada for two weeks?", "EMP-001"),
    ("May I work remotely from France for a month?", "EMP-002"),
    ("Can I temporarily work abroad while visiting family?", "EMP-003"),
    ("Can I work from another state for six weeks?", "EMP-004"),
    ("What approval do I need to work from Japan?", "EMP-005"),
])
def test_deterministic_remote_cases_require_confirmation(monkeypatch, query, employee_id) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer(query, employee_id)
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents", "get_policy_section", "check_policy_compliance",
    ]
    assert response.citations
    assert response.escalated is True
    assert response.requires_confirmation is True
    assert "create_mock_hr_ticket" not in tool_names(response)


@pytest.mark.parametrize("query", [
    "Can I work for 4 months from Thailand?",
    "Can I work for three months from Pakistan?",
    "Could I work temporarily from Germany while visiting family?",
])
def test_country_based_work_arrangements_use_remote_workflow(monkeypatch, query) -> None:
    """Location phrases must remain safe when the LLM router is unavailable."""
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer(query, "EMP-002")
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents", "get_policy_section", "check_policy_compliance",
    ]
    assert response.escalated is True
    assert response.requires_confirmation is True
    assert response.citations[0]["doc_id"] == "POL-RW-001"
    assert "not automatically covered by your current work arrangement" in response.answer
    assert "2. Eligibility" in response.answer
    assert "Would you like me to create an HR review request?" in response.answer
    assert "[OFFICIAL POLICY]" not in response.answer


def test_domestic_remote_request_does_not_claim_international_travel(monkeypatch) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer("I want to work from another state for two weeks", "EMP-005")
    assert response.requires_confirmation is True
    assert "another country" not in response.answer.lower()
    assert "overseas" not in response.answer.lower()


def test_remote_proposal_does_not_echo_follow_up_ticket_question(monkeypatch) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer(
        "I want to work from another state for 2 weeks. Can you create a ticket for me?", "EMP-005"
    )
    assert "Working from another state for 2 weeks is not automatically" in response.answer
    assert "Working from another state for 2 weeks. Can you" not in response.answer


def test_remote_approval_information_does_not_offer_to_create_ticket(monkeypatch) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer("How do I request remote work approval?", "EMP-002")
    assert response.requires_confirmation is False
    assert "create_mock_hr_ticket" not in tool_names(response)
    assert "approval" in response.answer.lower()


@pytest.mark.parametrize("query,expected_text,expected_docs", [
    ("Can I expense a standing desk and also claim a home office stipend as a remote employee?",
     "$500", {"POL-RW-001", "POL-EXP-001"}),
    ("As a remote employee, what data security rules apply to my home office setup?",
     "vpn", {"POL-RW-001", "POL-SEC-004"}),
    ("Can I work remotely from another country and also expense my internet connection there?",
     "$50/month", {"POL-RW-001", "POL-EXP-001"}),
    ("Can I use personal AI tools for work, and does that affect data security compliance?",
     "approved", {"POL-AIU-017", "POL-SEC-004"}),
])
def test_mixed_policy_questions_answer_all_topics(monkeypatch, query, expected_text, expected_docs) -> None:
    # Even an incorrect single-workflow LLM label cannot suppress the other policy topic.
    monkeypatch.setattr(orchestrator, "classify_workflow", lambda _query: "remote")
    response = _agent().answer(query, "EMP-001")
    assert expected_text.lower() in response.answer.lower()
    assert expected_docs.issubset({citation["doc_id"] for citation in response.citations})
    assert "another country for an extended period" not in response.answer.lower()
    assert response.requires_confirmation is False


def test_parental_leave_accrual_does_not_invent_a_rule(monkeypatch) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer("Does my PTO continue to accrue during parental leave?", "EMP-002")
    assert "neither policy states" in response.answer.lower()
    assert {"POL-PTO-002", "POL-LOA-008"}.issubset({c["doc_id"] for c in response.citations})


@pytest.mark.parametrize("query", [
    "What is the best coffee shop near the office?",
    "Can you write my quarterly performance self-review for me?",
])
def test_out_of_scope_requests_do_not_claim_policy_evidence(monkeypatch, query) -> None:
    monkeypatch.setattr(orchestrator, "classify_workflow", lambda _query: "policy")
    response = _agent().answer(query, "EMP-001")
    assert response.escalated is True
    assert response.citations == []
    assert response.tool_trace == []
    assert "outside" not in response.answer.lower() or "not that task" in response.answer.lower()


# ── Expense workflow ───────────────────────────────────────────────────────────

def test_expense_advisor_returns_policy_based_decision() -> None:
    response = _agent().answer("Can I expense a $1,200 standing desk?", "EMP-001")
    # Ergonomic purchases also retrieve the governing remote-work stipend.
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents",
        "get_policy_section", "get_policy_section", "check_policy_compliance",
    ]
    assert response.citations  # policy sources were retrieved


def test_ergonomic_mouse_uses_company_equipment_rule_not_desk_stipend(monkeypatch) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer("Can I expense a $150 ergonomic mouse for my home office?", "EMP-001")
    assert "mouse" in response.answer.lower()
    assert "company-provided" in response.answer.lower()
    assert "standing desk" not in response.answer.lower()


def test_expense_answer_is_non_empty() -> None:
    response = _agent().answer("Can I expense a $300 webcam for my home office?", "EMP-001")
    assert len(response.answer) > 20  # LLM answer or template fallback — both are non-trivial


def test_expense_escalated_reflects_compliance_result() -> None:
    response = _agent().answer("Can I expense a $1,200 standing desk?", "EMP-001")
    compliance_step = next(s for s in response.tool_trace if s["tool"] == "check_policy_compliance")
    assert response.escalated is (not compliance_step["result"]["compliant"])


@pytest.mark.parametrize("query,employee_id", [
    ("What is my per diem meal limit?", "EMP-001"),
    ("Can I expense a $200 monitor for my home office?", "EMP-002"),
    ("Can I get reimbursed for a client dinner?", "EMP-003"),
    ("Can I submit mileage for a customer visit?", "EMP-004"),
    ("Is a hotel charge reimbursable for business travel?", "EMP-005"),
])
def test_deterministic_expense_cases(monkeypatch, query, employee_id) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer(query, employee_id)
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents",
        "get_policy_section", "check_policy_compliance",
    ]
    assert response.citations
    compliance_step = next(s for s in response.tool_trace if s["tool"] == "check_policy_compliance")
    assert response.escalated is (not compliance_step["result"]["compliant"])


# ── Additional deterministic general-policy cases ─────────────────────────────

@pytest.mark.parametrize("query,employee_id", [
    ("Can I accept a $50 gift card from a vendor?", "EMP-001"),
    ("Can a vendor pay for my conference hotel?", "EMP-002"),
    ("What is the conflict of interest policy?", "EMP-003"),
    ("Are employees allowed to accept supplier event tickets?", "EMP-004"),
    ("Where can I find the code of conduct policy?", "EMP-005"),
])
def test_deterministic_general_policy_cases(monkeypatch, query, employee_id) -> None:
    _force_deterministic_routing(monkeypatch)
    response = _agent().answer(query, employee_id)
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents", "check_policy_compliance",
    ]
    assert response.citations
    assert response.requires_confirmation is False
