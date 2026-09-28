"""
Evaluation runner for the Acme HR Agent.

Usage:
    python evaluation/eval_runner.py
    python evaluation/eval_runner.py --endpoint https://acme-hr-agent.onrender.com
    python evaluation/eval_runner.py --top-k 3   # labels results for ablation; requires API support
    python evaluation/eval_runner.py --questions evaluation/questions.json --out evaluation/results.csv

Metrics per question:
  - escalation_match   : response.escalated == expected_escalated
  - tool_recall        : fraction of expected_tools found in tool_trace
  - citation_recall    : fraction of expected_citation_docs found in citations
  - keyword_match      : fraction of gold_keywords found in answer text
  - action_safety      : create_mock_hr_ticket only called when confirmed=True

Aggregate metrics reported:
  - per-metric accuracy (0–1)
  - latency p50 / p95 (ms)
  - overall pass rate (all metrics pass)
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Acme HR Agent eval runner")
    p.add_argument("--endpoint", default="http://127.0.0.1:8000",
                   help="Base URL of the FastAPI app (default: http://127.0.0.1:8000)")
    p.add_argument("--questions", default="evaluation/questions.json",
                   help="Path to questions.json (default: evaluation/questions.json)")
    p.add_argument("--out", default="evaluation/results.csv",
                   help="Path for output CSV (default: evaluation/results.csv)")
    p.add_argument("--top-k", type=int, default=None,
                   help="RAG top-k for ablation (label only; requires /chat to accept top_k param)")
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
    return True


def _overall_pass(row: dict) -> bool:
    return (
        row["escalation_match"]
        and row["tool_recall"] >= 0.5
        and row["citation_recall"] >= 0.5
        and row["keyword_match"] >= 0.5
        and row["action_safety"]
    )

# ── Request ───────────────────────────────────────────────────────────────────

def _call_chat(endpoint: str, q: dict, top_k: int | None, timeout: float) -> tuple[dict, float]:
    url = endpoint.rstrip("/") + "/chat"
    payload: dict[str, Any] = {
        "query":       q["query"],
        "employee_id": q["employee_id"],
        "confirmed":   bool(q.get("confirmed", False)),
    }
    if top_k is not None:
        payload["top_k"] = top_k

    t0 = time.perf_counter()
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
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

    questions_path = Path(args.questions)
    if not questions_path.exists():
        print(f"ERROR: questions file not found: {questions_path}", file=sys.stderr)
        return 1

    questions = json.loads(questions_path.read_text())["questions"]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Endpoint : {args.endpoint}")
    print(f"Questions: {len(questions)}")
    if args.top_k:
        print(f"Top-k    : {args.top_k} (ablation label)")
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
        "top_k",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for q in questions:
            qid = q["id"]
            print(f"  {qid} [{q['category']}] {q['query'][:60]}...")
            response, latency_ms = _call_chat(args.endpoint, q, args.top_k, args.timeout)
            latencies.append(latency_ms)

            tool_recall     = _tool_recall(response, q)
            citation_recall = _citation_recall(response, q)
            keyword_match   = _keyword_match(response, q)
            esc_match       = _escalation_match(response, q)
            act_safety      = _action_safety(response, q)

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
                "expected_tools":       "|".join(q.get("expected_tools") or []),
                "citations_returned":   "|".join(cited_ids),
                "expected_citations":   "|".join(q.get("expected_citation_docs") or []),
                "answer_snippet":       (response.get("answer") or "")[:120].replace("\n", " "),
                "top_k":                args.top_k or "",
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
    p95 = latencies_sorted[int(0.95 * n) - 1] if n >= 20 else latencies_sorted[-1]

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
