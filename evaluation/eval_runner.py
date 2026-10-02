"""
Evaluation runner for the Acme HR Agent.

Usage:
    python evaluation/eval_runner.py
    python evaluation/eval_runner.py --endpoint https://hrapp.elcaro.io
    PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py --top-k 3
    python evaluation/eval_runner.py --questions evaluation/questions.json --out evaluation/results.csv

Metrics include escalation/clarification, tool recall and selection F1,
evidence-backed citation accuracy, keyword match, workflow completion,
action safety, a lexical groundedness proxy, and request latency.

Normal runs force confirmed=False to avoid creating tickets. Only
--allow-write-actions permits confirmed test cases to write demo tickets.

Aggregate metrics reported:
  - per-metric accuracy (0–1)
  - latency p50 / p95 (ms)
  - overall pass rate (all metrics pass)
"""
from __future__ import annotations

import argparse
import csv
from contextlib import ExitStack
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Acme HR Agent eval runner")
    p.add_argument("--endpoint", default="http://127.0.0.1:8080",
                   help="Base URL of the FastAPI app (default: http://127.0.0.1:8080)")
    p.add_argument("--questions", default="evaluation/questions.json",
                   help="Path to questions.json (default: evaluation/questions.json)")
    p.add_argument("--out", default="evaluation/results.csv",
                   help="Path for output CSV (default: evaluation/results.csv)")
    p.add_argument("--top-k", type=int, choices=range(1, 21), default=5,
                   metavar="1..20", help="Actual policy-search retrieval top-k (default: 5)")
    p.add_argument("--password-env", default="PORTAL_EVAL_PASSWORD",
                   help="Environment variable containing the demo employee password")
    p.add_argument("--allow-write-actions", action="store_true",
                   help="Allow confirmed cases to create tickets (only for disposable data)")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="Per-request timeout in seconds (default: 60)")
    return p.parse_args()

# ── Scoring helpers ───────────────────────────────────────────────────────────

def _escalation_match(response: dict, q: dict) -> bool:
    return bool(response.get("escalated")) == bool(q["expected_escalated"])


def _tool_recall(response: dict, q: dict) -> float:
    expected = q.get("expected_tools") or []
    if not expected:
        return 1.0
    called = {t["tool"] for t in (response.get("tool_trace") or [])}
    return sum(1 for t in expected if t in called) / len(expected)


def _citation_recall(response: dict, q: dict) -> float:
    expected = q.get("expected_citation_docs") or []
    if not expected:
        return 1.0
    cited_ids = {c.get("doc_id", "") for c in (response.get("citations") or [])}
    return sum(1 for d in expected if d in cited_ids) / len(expected)


def _keyword_match(response: dict, q: dict) -> float:
    keywords = q.get("gold_keywords") or []
    if not keywords:
        return 1.0
    answer_lower = (response.get("answer") or "").lower()
    return sum(1 for kw in keywords if kw.lower() in answer_lower) / len(keywords)


def _action_safety(response: dict, q: dict) -> bool:
    """create_mock_hr_ticket must only appear in tool_trace when confirmed=True."""
    confirmed = bool(q.get("confirmed", False))
    tool_trace = response.get("tool_trace") or []
    ticket_called = any(t.get("tool") == "create_mock_hr_ticket" for t in tool_trace)
    if ticket_called and not confirmed:
        return False
    if q.get("expected_confirmation") and not response.get("requires_confirmation"):
        return False
    return True


def _called_tools(response: dict) -> set[str]:
    return {item.get("tool", "") for item in response.get("tool_trace") or []}


def _tool_selection_accuracy(response: dict, q: dict) -> float:
    """Tool-selection F1 penalizes both missing and unnecessary calls."""
    expected = set(q.get("expected_tools") or [])
    called = _called_tools(response)
    if not expected and not called:
        return 1.0
    return 2 * len(expected & called) / (len(expected) + len(called))


def _citation_accuracy(response: dict) -> float:
    """Verify cited document/section pairs against retrieved tool evidence."""
    citations = response.get("citations") or []
    if not citations:
        answer = response.get("answer") or ""
        return 0.0 if response.get("snippets") or "[OFFICIAL POLICY]" in answer else 1.0
    evidence = set()
    for call in response.get("tool_trace") or []:
        result = call.get("result") or {}
        for chunk in result.get("chunks") or []:
            evidence.add((chunk.get("doc_id"), chunk.get("section")))
        if result.get("found") and result.get("doc_id"):
            evidence.add((result.get("doc_id"), result.get("section")))
    return sum((item.get("doc_id"), item.get("section")) in evidence for item in citations) / len(citations)


def _groundedness_proxy(response: dict) -> float:
    """Lexical overlap with policy and structured tool evidence, not entailment."""
    answer = response.get("answer") or ""
    evidence_parts = []
    for call in response.get("tool_trace") or []:
        result = call.get("result") or {}
        evidence_parts.extend(chunk.get("text", "") for chunk in result.get("chunks") or [])
        if result.get("found") and result.get("text"):
            evidence_parts.append(result["text"])
        if call.get("tool") in ("lookup_employee_profile", "check_pto_balance"):
            evidence_parts.append(json.dumps(result, default=str))
    evidence = " ".join(evidence_parts)
    if not evidence:
        return 1.0 if "[OFFICIAL POLICY]" not in answer else 0.0
    stop = {"about", "after", "before", "could", "from", "have", "into", "their", "there",
            "these", "those", "which", "would", "your", "with", "this", "that", "policy"}
    words = {word for word in re.findall(r"[a-z]{5,}", answer.lower()) if word not in stop}
    evidence_words = set(re.findall(r"[a-z]{5,}", evidence.lower()))
    return len(words & evidence_words) / len(words) if words else 1.0


def _clarification_accuracy(response: dict, q: dict) -> bool:
    if q.get("category") != "ambiguous":
        return True
    answer = (response.get("answer") or "").lower()
    return bool(re.search(r"\?|clarif|which|what (?:kind|type|item|date)|more detail", answer))


def _workflow_completion(response: dict, q: dict) -> bool:
    if (response.get("answer") or "").startswith(("[HTTP", "[TIMEOUT")):
        return False
    if q.get("category") == "out_of_scope":
        return not _called_tools(response) and not response.get("citations") and bool(response.get("escalated"))
    if q.get("category") == "ambiguous" and not _clarification_accuracy(response, q):
        return False
    return set(q.get("expected_tools") or []).issubset(_called_tools(response)) and _action_safety(response, q)


def _effective_case(q: dict, allow_write_actions: bool) -> dict:
    effective = dict(q)
    if not allow_write_actions:
        effective["expected_confirmation"] = bool(q.get("confirmed", False))
        effective["confirmed"] = False
        effective["expected_tools"] = [tool for tool in q.get("expected_tools") or []
                                       if tool != "create_mock_hr_ticket"]
    return effective


def _overall_pass(row: dict) -> bool:
    return (
        row["escalation_match"]
        and row["tool_recall"] >= 0.5
        and row["citation_recall"] >= 0.5
        and row["keyword_match"] >= 0.5
        and row["action_safety"]
        and row["tool_selection_accuracy"] >= 0.6
        and row["citation_accuracy"] >= 0.8
        and row["clarification_accuracy"]
        and row["workflow_completion"]
    )

# ── Request ───────────────────────────────────────────────────────────────────

def _call_chat(client: httpx.Client, endpoint: str, q: dict, top_k: int, timeout: float) -> tuple[dict, float]:
    url = endpoint.rstrip("/") + "/chat"
    payload: dict[str, Any] = {
        "query":       q["query"],
        "employee_id": q["employee_id"],
        "confirmed":   bool(q.get("confirmed", False)),
    }
    payload["top_k"] = top_k

    t0 = time.perf_counter()
    try:
        r = client.post(url, json=payload, timeout=timeout)
        latency_ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        return r.json(), latency_ms
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"answer": "[TIMEOUT]", "escalated": True, "tool_trace": [], "citations": []}, latency_ms
    except httpx.HTTPStatusError as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"answer": f"[HTTP {exc.response.status_code}]", "escalated": True, "tool_trace": [], "citations": []}, latency_ms

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()
    password = os.getenv(args.password_env)
    if not password:
        print(f"ERROR: set {args.password_env} to the demo employee password", file=sys.stderr)
        return 2

    questions_path = Path(args.questions)
    if not questions_path.exists():
        print(f"ERROR: questions file not found: {questions_path}", file=sys.stderr)
        return 1

    questions = json.loads(questions_path.read_text(encoding="utf-8"))["questions"]
    gold_path = questions_path.with_name("gold_answers.json")
    gold_answers = json.loads(gold_path.read_text(encoding="utf-8"))
    if {q["id"] for q in questions} != set(gold_answers):
        raise ValueError("Gold answers must cover exactly the evaluation question IDs")
    for question in questions:
        question["gold_answer"] = gold_answers[question["id"]]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Endpoint : {args.endpoint}")
    print(f"Questions: {len(questions)}")
    print(f"Top-k    : {args.top_k} (applied to policy search)")
    if not args.allow_write_actions:
        print("Safety   : confirmed actions disabled; no evaluation tickets created")
    print()

    rows: list[dict] = []
    latencies: list[float] = []

    fieldnames = [
        "id", "category", "query", "employee_id", "latency_ms",
        "escalation_match", "tool_recall", "citation_recall", "keyword_match",
        "action_safety", "overall_pass",
        "response_escalated", "expected_escalated",
        "tools_called", "expected_tools",
        "citations_returned", "expected_citations",
        "answer_snippet",
        "top_k", "effective_confirmed", "tool_selection_accuracy", "citation_accuracy",
        "groundedness_proxy", "clarification_accuracy", "workflow_completion", "gold_answer",
        "requires_confirmation", "expected_confirmation", "answer",
    ]

    with ExitStack() as stack, open(out_path, "w", newline="", encoding="utf-8") as f:
        clients: dict[str, httpx.Client] = {}
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for q in questions:
            qid = q["id"]
            print(f"  {qid} [{q['category']}] {q['query'][:60]}...")
            employee_id = q["employee_id"]
            if employee_id not in clients:
                client = stack.enter_context(httpx.Client(timeout=args.timeout))
                login = client.post(args.endpoint.rstrip("/") + "/login",
                                    data={"employee_id": employee_id, "password": password})
                if login.status_code != 200:
                    raise RuntimeError(f"Sign-in failed for {employee_id}: HTTP {login.status_code}")
                clients[employee_id] = client
            effective_q = _effective_case(q, args.allow_write_actions)
            response, latency_ms = _call_chat(clients[employee_id], args.endpoint, effective_q,
                                              args.top_k, args.timeout)
            latencies.append(latency_ms)

            tool_recall     = _tool_recall(response, effective_q)
            citation_recall = _citation_recall(response, effective_q)
            keyword_match   = _keyword_match(response, effective_q)
            esc_match       = _escalation_match(response, effective_q)
            act_safety      = _action_safety(response, effective_q)

            tools_called = [t.get("tool", "") for t in (response.get("tool_trace") or [])]
            cited_ids    = [c.get("doc_id", "") for c in (response.get("citations") or [])]

            row = {
                "id":                   qid,
                "category":             q["category"],
                "query":                q["query"],
                "employee_id":          q["employee_id"],
                "latency_ms":           round(latency_ms, 1),
                "escalation_match":     esc_match,
                "tool_recall":          round(tool_recall, 3),
                "citation_recall":      round(citation_recall, 3),
                "keyword_match":        round(keyword_match, 3),
                "action_safety":        act_safety,
                "overall_pass":         False,
                "response_escalated":   response.get("escalated"),
                "expected_escalated":   q["expected_escalated"],
                "tools_called":         "|".join(tools_called),
                "expected_tools":       "|".join(effective_q.get("expected_tools") or []),
                "citations_returned":   "|".join(cited_ids),
                "expected_citations":   "|".join(q.get("expected_citation_docs") or []),
                "answer_snippet":       (response.get("answer") or "")[:120].replace("\n", " "),
                "top_k":                args.top_k,
                "effective_confirmed": effective_q["confirmed"],
                "tool_selection_accuracy": round(_tool_selection_accuracy(response, effective_q), 3),
                "citation_accuracy": round(_citation_accuracy(response), 3),
                "groundedness_proxy": round(_groundedness_proxy(response), 3),
                "clarification_accuracy": _clarification_accuracy(response, effective_q),
                "workflow_completion": _workflow_completion(response, effective_q),
                "gold_answer": q.get("gold_answer", ""),
                "requires_confirmation": bool(response.get("requires_confirmation", False)),
                "expected_confirmation": bool(effective_q.get("expected_confirmation", False)),
                "answer": (response.get("answer") or "")[:3_000],
            }
            row["overall_pass"] = _overall_pass(row)
            rows.append(row)
            writer.writerow(row)

            status = "PASS" if row["overall_pass"] else "FAIL"
            print(f"         {status}  latency={latency_ms:.0f}ms  "
                  f"esc={esc_match}  tools={tool_recall:.2f}  "
                  f"cit={citation_recall:.2f}  kw={keyword_match:.2f}  "
                  f"safety={act_safety}")

    # ── Aggregate report ──────────────────────────────────────────────────────
    n = len(rows)
    latencies_sorted = sorted(latencies)
    p50 = statistics.median(latencies_sorted)
    p95 = latencies_sorted[math.ceil(0.95 * n) - 1]

    def _pct(key: str) -> float:
        return sum(1 for r in rows if r[key]) / n if n else 0.0

    print()
    print("=" * 60)
    print(f"EVALUATION RESULTS  ({n} questions)")
    print("=" * 60)
    print(f"  Overall pass rate   : {_pct('overall_pass'):.1%}")
    print(f"  Escalation accuracy : {_pct('escalation_match'):.1%}")
    print(f"  Tool recall (avg)   : {sum(r['tool_recall'] for r in rows)/n:.1%}")
    print(f"  Citation recall(avg): {sum(r['citation_recall'] for r in rows)/n:.1%}")
    print(f"  Keyword match (avg) : {sum(r['keyword_match'] for r in rows)/n:.1%}")
    print(f"  Action safety       : {_pct('action_safety'):.1%}")
    print(f"  Tool selection F1   : {sum(r['tool_selection_accuracy'] for r in rows)/n:.1%}")
    print(f"  Citation accuracy   : {sum(r['citation_accuracy'] for r in rows)/n:.1%}")
    print(f"  Groundedness proxy  : {sum(r['groundedness_proxy'] for r in rows)/n:.1%}")
    print(f"  Clarification       : {_pct('clarification_accuracy'):.1%}")
    print(f"  Workflow completion : {_pct('workflow_completion'):.1%}")
    print(f"  Latency p50         : {p50:.0f} ms")
    print(f"  Latency p95         : {p95:.0f} ms")
    print()
    print(f"Results written to: {out_path}")

    # Per-category breakdown
    categories = sorted({r["category"] for r in rows})
    print()
    print("Per-category pass rate:")
    for cat in categories:
        cat_rows = [r for r in rows if r["category"] == cat]
        passed   = sum(1 for r in cat_rows if r["overall_pass"])
        print(f"  {cat:<14} {passed}/{len(cat_rows)}")

    return 0 if _pct("overall_pass") >= 0.7 else 1


if __name__ == "__main__":
    sys.exit(main())
