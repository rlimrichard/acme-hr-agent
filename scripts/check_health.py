"""Fail deployment unless the app, MCP server, and policy index are healthy."""

from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def health_errors(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return ["health response is not a JSON object"]

    errors = []
    if payload.get("status") != "ok":
        errors.append("status is not ok")
    if payload.get("mcp_connected") is not True:
        errors.append("MCP is not connected")
    if payload.get("chroma_loaded") is not True:
        errors.append("policy index is not loaded")
    doc_count = payload.get("doc_count")
    if type(doc_count) is not int or doc_count <= 0:
        errors.append("policy index has no documents")
    tool_count = payload.get("tool_count")
    if type(tool_count) is not int or tool_count < 8:
        errors.append("fewer than eight MCP tools were discovered")
    return errors


def main(url: str) -> int:
    try:
        with urlopen(url, timeout=5) as response:
            payload = json.load(response)
    except (URLError, OSError, ValueError) as exc:
        print(f"Health check failed: {exc}", file=sys.stderr)
        return 1

    errors = health_errors(payload)
    if errors:
        print(f"Health check failed: {', '.join(errors)}; response={payload}", file=sys.stderr)
        return 1
    print(f"Health check passed: {payload}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_health.py URL", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
