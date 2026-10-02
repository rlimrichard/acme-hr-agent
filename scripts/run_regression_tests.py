"""Run the workflow regression suite and save its latest result for /admin."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT_FILE = ROOT / "logs" / "latest_regression_tests.json"


def _count(output: str, label: str) -> int:
    match = re.search(rf"(\d+)\s+{label}", output)
    return int(match.group(1)) if match else 0


def main() -> int:
    environment = os.environ.copy()
    # Keep this deterministic: the workflow tests exercise the local fallback,
    # rather than depending on an external model provider during deployment.
    environment["OPENROUTER_API_KEY"] = ""
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_reasoning_workflows.py", "-q"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    passed = _count(output, "passed")
    failed = _count(output, "failed")
    errors = _count(output, "errors?")
    result = {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "passed" if completed.returncode == 0 else "failed",
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
        "duration_seconds": round(time.monotonic() - started, 2),
        "command": "python -m pytest tests/test_reasoning_workflows.py -q",
        "output": output[-12_000:],
    }
    RESULT_FILE.parent.mkdir(exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(output)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
