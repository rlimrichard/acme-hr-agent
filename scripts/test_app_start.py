"""Start the production ASGI app and verify HTTP health and MCP discovery."""

from __future__ import annotations

import subprocess
import sys
import time

import httpx

from src.agent.orchestrator import MCPClient


def main() -> int:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.app.main:app", "--host", "127.0.0.1", "--port", "18080"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"App exited during startup: {process.stderr.read().decode(errors='replace')[-4000:]}")
            try:
                response = httpx.get("http://127.0.0.1:18080/health", timeout=3)
                health = response.json()
                if (response.status_code == 200 and health.get("status") == "ok"
                        and health.get("chroma_loaded") and health.get("doc_count", 0) > 0):
                    tools = MCPClient().discover_tools()
                    assert len(tools) == 8, f"Expected 8 MCP tools, got {len(tools)}"
                    print("App startup, /health, and MCP discovery passed")
                    return 0
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("App did not reach healthy state within 90 seconds")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
