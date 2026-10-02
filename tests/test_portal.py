import json

import pytest
from fastapi.testclient import TestClient

from src.app import main, portal


@pytest.fixture
def portal_client(monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(portal, "TICKETS_FILE", tmp_path / "tickets.jsonl")
    monkeypatch.setattr(portal, "REVIEWS_FILE", tmp_path / "reviews.jsonl")
    portal.USERS_FILE.write_text(json.dumps({
        item["employee_id"]: portal.password_hash("acme123") for item in main._employee_records()
    }), encoding="utf-8")
    portal.TICKETS_FILE.write_text(json.dumps({
        "ticket_id": "TKT-TEST", "employee_id": "EMP-001", "ticket_type": "general_inquiry",
        "subject": "Remote work", "description": "Four months abroad", "status": "created",
        "created_at": "2026-01-01T00:00:00Z",
    }) + "\n" + json.dumps({
        "ticket_id": "TKT-PTO", "employee_id": "EMP-001", "ticket_type": "pto_request",
        "subject": "PTO", "description": "Three days off", "status": "created",
        "created_at": "2026-01-02T00:00:00Z",
    }) + "\n", encoding="utf-8")
    return TestClient(main.app)


def login(client, employee_id):
    return client.post("/login", data={"employee_id": employee_id, "password": "acme123"})


def test_login_and_employee_scope(portal_client):
    client = portal_client
    assert client.get("/portal/tickets").status_code == 401
    assert client.post("/login", data={"employee_id": "EMP-001", "password": "wrong"}).status_code == 401
    assert login(client, "EMP-001").status_code == 200
    data = client.get("/portal/tickets").json()
    assert {item["ticket_id"] for item in data["my_pending"]} == {"TKT-TEST", "TKT-PTO"}
    assert not data["hr_queue"] and not data["manager_queue"]
    assert client.post("/portal/tickets/TKT-PTO/review", json={"decision": "approved", "message": "Yes"}).status_code == 403
    assert client.post("/chat", json={"query": "What can you do?", "employee_id": "EMP-002"}).status_code == 403


def test_hr_and_manager_queues_and_review(portal_client):
    client = portal_client
    assert login(client, "EMP-002").status_code == 200
    data = client.get("/portal/tickets").json()
    assert [item["ticket_id"] for item in data["hr_queue"]] == ["TKT-TEST"]
    assert not data["manager_queue"]
    assert client.post("/portal/tickets/TKT-PTO/review", json={"decision": "approved", "message": "Yes"}).status_code == 403
    assert client.post("/portal/tickets/TKT-TEST/review", json={"decision": "denied", "message": "Please remain in your current location."}).status_code == 200
    assert client.post("/portal/tickets/TKT-TEST/review", json={"decision": "approved", "message": "Changed mind"}).status_code == 409
    assert login(client, "EMP-004").status_code == 200
    data = client.get("/portal/tickets").json()
    assert [item["ticket_id"] for item in data["manager_queue"]] == ["TKT-PTO"]
    assert client.post("/portal/tickets/TKT-PTO/review", json={"decision": "approved", "message": "Approved; please update your calendar."}).status_code == 200
    assert login(client, "EMP-001").status_code == 200
    data = client.get("/portal/tickets").json()
    assert not data["my_pending"]
    assert {item["ticket_id"]: item["review_message"] for item in data["my_closed"]} == {
        "TKT-PTO": "Approved; please update your calendar.",
        "TKT-TEST": "Please remain in your current location.",
    }


def test_pto_request_requires_confirmation(monkeypatch):
    from src.agent.orchestrator import HRAgent
    from src.mcp.server import app as mcp_app
    import src.agent.orchestrator as orchestrator
    class LocalClient:
        def call(self, tool, args):
            response = TestClient(mcp_app).post(f"/tools/{tool}", json=args)
            response.raise_for_status()
            return response.json()
    monkeypatch.setattr(orchestrator, "classify_workflow", lambda _query: "pto")
    response = HRAgent(LocalClient()).answer("Submit a PTO request for three days next week", "EMP-001")
    assert response.requires_confirmation is True
    assert "create_mock_hr_ticket" not in [step["tool"] for step in response.tool_trace]
