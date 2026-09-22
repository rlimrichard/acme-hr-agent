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


def tool_names(response) -> list[str]:
    return [step["tool"] for step in response.tool_trace]


def test_discovers_eight_tools() -> None:
    response = TestClient(app).get("/tools")
    assert response.status_code == 200
    assert len(response.json()["tools"]) == 8


def test_pto_advisor_uses_profile_balance_policy_compliance_and_draft() -> None:
    response = HRAgent(LocalMCPClient()).answer("Can I take 3 weeks off in December?", "EMP-002")
    assert tool_names(response) == [
        "lookup_employee_profile", "check_pto_balance", "search_policy_documents",
        "check_policy_compliance", "draft_hr_email",
    ]
    assert response.citations


def test_remote_work_ticket_requires_explicit_confirmation() -> None:
    agent = HRAgent(LocalMCPClient())
    pending = agent.answer("Can I work from Spain for 6 weeks?", "EMP-001")
    assert pending.requires_confirmation is True
    assert "create_mock_hr_ticket" not in tool_names(pending)

    confirmed = agent.answer("Can I work from Spain for 6 weeks?", "EMP-001", confirmed=True)
    assert tool_names(confirmed)[-1] == "create_mock_hr_ticket"


def test_expense_advisor_returns_policy_based_decision() -> None:
    response = HRAgent(LocalMCPClient()).answer("Can I expense a $1,200 standing desk?", "EMP-001")
    assert tool_names(response) == ["lookup_employee_profile", "search_policy_documents", "check_policy_compliance"]
    assert "pre-approval" in response.answer.lower()
