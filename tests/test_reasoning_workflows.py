import pytest
from fastapi.testclient import TestClient

from src.agent.orchestrator import HRAgent
from src.mcp.server import app


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


# ── Tool discovery ─────────────────────────────────────────────────────────────

def test_discovers_eight_tools() -> None:
    response = TestClient(app).get("/tools")
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 8


# ── _kind() routing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("Can I take some time off next week?",        "pto"),
    ("I need 2 weeks vacation in December",        "pto"),
    ("I'm requesting PTO for next Friday",         "pto"),
    ("I want to work from Spain for a month",      "remote"),
    ("Can I work from home abroad?",               "remote"),
    ("Can I expense a $500 monitor?",              "expense"),
    ("I need to reimburse my standing desk",       "expense"),
    ("What is the office kitchen cleaning rota?",  "policy"),
    ("Can I receive a $1,000 gift from a vendor?", "policy"),
])
def test_kind_routing(query: str, expected: str) -> None:
    assert HRAgent._kind(query) == expected


# ── General policy workflow ───────────────────────────────────────────────────

def test_general_policy_query_retrieves_before_answering() -> None:
    response = _agent().answer("Can I receive a $1,000 gift from a vendor?", "EMP-001")
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents", "check_policy_compliance",
    ]
    assert response.citations


# ── Response structure ────────────────────────────────────────────────────────

def test_response_as_dict_has_all_required_keys() -> None:
    d = _agent().answer("Can I take a day off?", "EMP-001").as_dict()
    for key in ("answer", "citations", "snippets", "tool_trace", "escalated", "requires_confirmation"):
        assert key in d, f"missing key: {key}"


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


def test_pto_employee_not_found_escalates() -> None:
    response = _agent().answer("Can I take a day off?", "EMP-999")
    assert response.escalated is True


# ── Remote work workflow ──────────────────────────────────────────────────────

def test_remote_work_requires_confirmation_before_ticket() -> None:
    # Without confirmed=True, no ticket should be created and confirmation is requested
    response = _agent().answer("Can I work from Spain for 6 weeks?", "EMP-001")
    assert response.requires_confirmation is True
    assert "create_mock_hr_ticket" not in tool_names(response)


def test_remote_work_ticket_created_when_confirmed() -> None:
    # With confirmed=True, ticket should be created
    response = _agent().answer("Can I work from Spain for 6 weeks?", "EMP-001", confirmed=True)
    assert response.requires_confirmation is False
    assert "create_mock_hr_ticket" in tool_names(response)


def test_remote_work_always_escalated() -> None:
    response = _agent().answer("I want to work remotely from another country for 3 months", "EMP-003")
    assert response.escalated is True


# ── Expense workflow ───────────────────────────────────────────────────────────

def test_expense_advisor_returns_policy_based_decision() -> None:
    response = _agent().answer("Can I expense a $1,200 standing desk?", "EMP-001")
    # expense_advisor runs 4 steps: profile → search → section → compliance
    assert tool_names(response) == [
        "lookup_employee_profile", "search_policy_documents",
        "get_policy_section", "check_policy_compliance",
    ]
    assert response.citations  # policy sources were retrieved


def test_expense_answer_is_non_empty() -> None:
    response = _agent().answer("Can I expense a $300 webcam for my home office?", "EMP-001")
    assert len(response.answer) > 20  # LLM answer or template fallback — both are non-trivial


def test_expense_escalated_reflects_compliance_result() -> None:
    response = _agent().answer("Can I expense a $1,200 standing desk?", "EMP-001")
    compliance_step = next(s for s in response.tool_trace if s["tool"] == "check_policy_compliance")
    assert response.escalated is (not compliance_step["result"]["compliant"])
