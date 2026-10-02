"""Verify actual MCP discovery and invocation, not just the legacy REST routes."""

import asyncio

from mcp.client import Client

from src.mcp.server import mcp


def test_mcp_discovery_and_employee_tool() -> None:
    async def check() -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 8
            assert "lookup_employee_profile" in {tool.name for tool in tools.tools}
            result = await client.call_tool("lookup_employee_profile", {"employee_id": "EMP-001"})
            assert not result.is_error
            assert result.structured_content["employee_id"] == "EMP-001"
            assert result.structured_content["found"] is True

    asyncio.run(check())
