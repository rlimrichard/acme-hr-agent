"""Run the workflow regression suite and save its latest result for /admin."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
RESULT_FILE = ROOT / "logs" / "latest_regression_tests.json"


def _count(output: str, label: str) -> int:
    match = re.search(rf"(\d+)\s+{label}", output)
    return int(match.group(1)) if match else 0


def parse_junit_cases(report_path: Path) -> list[dict[str, object]]:
    """Read pytest's built-in JUnit report so each case survives beyond console output."""
    if not report_path.is_file():
        return []
    try:
        root = ElementTree.parse(report_path).getroot()
    except ElementTree.ParseError:
        return []
    cases = []
    for case in root.findall(".//testcase"):
        issue = next((case.find(tag) for tag in ("failure", "error", "skipped")
                      if case.find(tag) is not None), None)
        status = "failed" if issue is not None and issue.tag == "failure" else (issue.tag if issue is not None else "passed")
        cases.append({
            "name": case.get("name", "Unnamed test"),
            "suite": case.get("classname", ""),
            "status": status,
            "duration_seconds": round(float(case.get("time", "0")), 3),
            "detail": ((issue.get("message", "") + "\n" + (issue.text or "")).strip()[:4_000]
                       if issue is not None else ""),
        })
    return cases


def main() -> int:
    environment = os.environ.copy()
    # Keep this deterministic: the workflow tests exercise the local fallback,
    # rather than depending on an external model provider during deployment.
    environment["OPENROUTER_API_KEY"] = ""
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as temporary_directory:
        report_path = Path(temporary_directory) / "regression-junit.xml"
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_reasoning_workflows.py", "-v",
             f"--junitxml={report_path}"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        cases = parse_junit_cases(report_path)
    output = (completed.stdout + completed.stderr).strip()
    passed = sum(case["status"] == "passed" for case in cases) if cases else _count(output, "passed")
    failed = sum(case["status"] == "failed" for case in cases) if cases else _count(output, "failed")
    errors = sum(case["status"] == "error" for case in cases) if cases else _count(output, "errors?")
    skipped = sum(case["status"] == "skipped" for case in cases) if cases else _count(output, "skipped")
    result = {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "passed" if completed.returncode == 0 else "failed",
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "total": passed + failed + errors + skipped,
        "duration_seconds": round(time.monotonic() - started, 2),
        "command": "python -m pytest tests/test_reasoning_workflows.py -v --junitxml=<temporary report>",
        "cases": cases,
        "output": output[-20_000:],
    }
    RESULT_FILE.parent.mkdir(exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(output)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
