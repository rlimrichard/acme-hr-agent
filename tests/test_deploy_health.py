"""The deploy gate must reject HTTP-200 responses with degraded JSON status."""

import io
import json

from scripts import check_health
from scripts.check_health import health_errors


HEALTHY = {
    "status": "ok",
    "mcp_connected": True,
    "chroma_loaded": True,
    "doc_count": 694,
    "tool_count": 8,
    "version": "0.1.0",
}


def test_healthy_response_passes() -> None:
    assert health_errors(HEALTHY) == []


def test_http_200_with_degraded_json_fails() -> None:
    degraded = {**HEALTHY, "status": "degraded", "mcp_connected": False, "tool_count": 0}
    assert health_errors(degraded)


def test_missing_index_or_malformed_counts_fail() -> None:
    assert health_errors({**HEALTHY, "chroma_loaded": False, "doc_count": 0})
    assert health_errors({**HEALTHY, "doc_count": True, "tool_count": "8"})
    assert health_errors([HEALTHY])


def test_cli_rejects_http_200_with_degraded_json(monkeypatch) -> None:
    payload = {**HEALTHY, "status": "degraded"}
    monkeypatch.setattr(check_health, "urlopen", lambda *_args, **_kwargs: io.BytesIO(json.dumps(payload).encode()))
    assert check_health.main("http://localhost/health") == 1
