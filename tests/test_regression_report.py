"""The admin report must preserve individual pytest outcomes, not only its summary."""

import json
import subprocess

from scripts import run_regression_tests


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="1" errors="0" skipped="1">
  <testcase classname="tests.test_reasoning_workflows" name="test_pto[three days-EMP-001]" time="0.125" />
  <testcase classname="tests.test_reasoning_workflows" name="test_remote[Thailand-EMP-002]" time="0.500">
    <failure message="Expected confirmation">AssertionError: missing confirmation</failure>
  </testcase>
  <testcase classname="tests.test_reasoning_workflows" name="test_skipped" time="0.000">
    <skipped message="not applicable" />
  </testcase>
</testsuite></testsuites>"""


def test_parse_junit_cases_preserves_parameterized_names_and_failures(tmp_path):
    report = tmp_path / "results.xml"
    report.write_text(JUNIT, encoding="utf-8")
    cases = run_regression_tests.parse_junit_cases(report)
    assert [case["status"] for case in cases] == ["passed", "failed", "skipped"]
    assert cases[0]["name"] == "test_pto[three days-EMP-001]"
    assert cases[0]["duration_seconds"] == 0.125
    assert "missing confirmation" in cases[1]["detail"]


def test_runner_persists_case_table(monkeypatch, tmp_path):
    results = tmp_path / "latest.json"
    monkeypatch.setattr(run_regression_tests, "RESULT_FILE", results)

    def fake_run(command, **_kwargs):
        report_arg = next(arg for arg in command if arg.startswith("--junitxml="))
        from pathlib import Path
        Path(report_arg.split("=", 1)[1]).write_text(JUNIT, encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, stdout="1 failed, 1 passed, 1 skipped", stderr="")

    monkeypatch.setattr(run_regression_tests.subprocess, "run", fake_run)
    assert run_regression_tests.main() == 1
    saved = json.loads(results.read_text(encoding="utf-8"))
    assert (saved["passed"], saved["failed"], saved["skipped"], saved["total"]) == (1, 1, 1, 3)
    assert len(saved["cases"]) == 3
    assert saved["cases"][1]["status"] == "failed"
