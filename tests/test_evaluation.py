"""Evaluation safety and measurement contracts."""

import json
from pathlib import Path

import httpx

from evaluation import eval_runner


def test_ablation_sends_actual_top_k() -> None:
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"answer": "ok", "tool_trace": [], "citations": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        case = {"query": "What is PTO?", "employee_id": "EMP-001", "confirmed": False}
        eval_runner._call_chat(client, "https://example.test", case, 3, 5)
        eval_runner._call_chat(client, "https://example.test", case, 8, 5)
    assert [payload["top_k"] for payload in payloads] == [3, 8]


def test_default_eval_cannot_create_ticket() -> None:
    case = {"confirmed": True, "expected_tools": ["search_policy_documents", "create_mock_hr_ticket"]}
    safe = eval_runner._effective_case(case, False)
    assert safe["confirmed"] is False
    assert safe["expected_confirmation"] is True
    assert safe["expected_tools"] == ["search_policy_documents"]
    assert case["confirmed"] is True


def test_citation_accuracy_uses_returned_evidence() -> None:
    response = {
        "citations": [{"doc_id": "POL-PTO-002", "section": "Approval"},
                      {"doc_id": "POL-FAKE-999", "section": "Unknown"}],
        "tool_trace": [{"result": {"chunks": [{"doc_id": "POL-PTO-002", "section": "Approval"}]}}],
    }
    assert eval_runner._citation_accuracy(response) == 0.5


def test_unconfirmed_write_case_must_offer_confirmation() -> None:
    case = eval_runner._effective_case({"confirmed": True, "expected_tools": []}, False)
    assert eval_runner._action_safety({"requires_confirmation": False, "tool_trace": []}, case) is False
    assert eval_runner._action_safety({"requires_confirmation": True, "tool_trace": []}, case) is True


def test_overall_pass_requires_supported_citations_and_completed_workflow() -> None:
    row = {"escalation_match": True, "tool_recall": 1, "citation_recall": 1,
           "keyword_match": 1, "action_safety": True, "tool_selection_accuracy": 1,
           "citation_accuracy": 1, "clarification_accuracy": True, "workflow_completion": True}
    assert eval_runner._overall_pass(row)
    assert not eval_runner._overall_pass({**row, "citation_accuracy": 0.5})
    assert not eval_runner._overall_pass({**row, "workflow_completion": False})


def test_all_25_cases_have_reference_answers() -> None:
    root = Path(__file__).parents[1] / "evaluation"
    questions = json.loads((root / "questions.json").read_text(encoding="utf-8"))["questions"]
    answers = json.loads((root / "gold_answers.json").read_text(encoding="utf-8"))
    assert len(questions) == 25
    assert {case["id"] for case in questions} == set(answers)
    assert all(answers.values())
