"""Summarize authenticated evaluation CSVs and a fixed 15-case latency sample.

Usage: python evaluation/summarize_results.py evaluation/results-current.csv
       python evaluation/summarize_results.py evaluation/results-k{3,5,8}-live.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


# Five direct policy, four multi-document, four agentic, one ambiguous, and
# one out-of-scope question. Fixed before measuring so runs are comparable.
LATENCY_SAMPLE_IDS = (
    "Q001", "Q002", "Q004", "Q006", "Q008",
    "Q009", "Q010", "Q012", "Q013",
    "Q014", "Q016", "Q017", "Q020",
    "Q021", "Q024",
)


def percentile_95(values: list[float]) -> float:
    if not values:
        raise ValueError("No latency values")
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def summarize(path: Path) -> dict[str, float | int | str]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 25 or len({r["id"] for r in rows}) != 25:
        raise ValueError(f"{path}: expected 25 unique evaluation rows")
    by_id = {r["id"]: r for r in rows}
    if missing := set(LATENCY_SAMPLE_IDS) - by_id.keys():
        raise ValueError(f"{path}: missing latency sample IDs {sorted(missing)}")

    sample = [float(by_id[qid]["latency_ms"]) for qid in LATENCY_SAMPLE_IDS]
    passes = sum(r["overall_pass"].lower() == "true" for r in rows)
    def mean(field: str) -> float:
        return sum(
            1.0 if r[field].lower() == "true" else
            0.0 if r[field].lower() == "false" else float(r[field])
            for r in rows
        ) / len(rows)
    return {
        "file": str(path),
        "top_k": int(rows[0]["top_k"]),
        "passed": passes,
        "total": len(rows),
        "tool_f1": mean("tool_selection_accuracy"),
        "citation_accuracy": mean("citation_accuracy"),
        "groundedness_proxy": mean("groundedness_proxy"),
        "workflow_completion": mean("workflow_completion"),
        "action_safety": sum(r["action_safety"].lower() == "true" for r in rows) / len(rows),
        "latency_sample_n": len(sample),
        "latency_p50_ms": statistics.median(sample),
        "latency_p95_ms": percentile_95(sample),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_files", nargs="+", type=Path)
    args = parser.parse_args()
    print("Fixed latency sample:", ", ".join(LATENCY_SAMPLE_IDS))
    for path in args.csv_files:
        result = summarize(path)
        print(
            f"{result['file']}: k={result['top_k']} "
            f"pass={result['passed']}/{result['total']} "
            f"tool_F1={result['tool_f1']:.1%} "
            f"citation_accuracy={result['citation_accuracy']:.1%} "
            f"groundedness_proxy={result['groundedness_proxy']:.1%} "
            f"workflow_completion={result['workflow_completion']:.1%} "
            f"action_safety={result['action_safety']:.1%} "
            f"latency_n={result['latency_sample_n']} "
            f"p50={result['latency_p50_ms']:.0f}ms "
            f"p95={result['latency_p95_ms']:.0f}ms"
        )


if __name__ == "__main__":
    main()
