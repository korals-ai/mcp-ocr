"""Tests for the MCP server wiring: the ``ocr`` tool registers and maps
failures to MCP errors. No real ocrmypdf (absent in CI) — that's the
integration suite's job against the running sidecar."""

from __future__ import annotations

import pytest

from src import server


@pytest.mark.asyncio
async def test_ocr_tool_is_registered() -> None:
    tools = await server.mcp.list_tools()
    assert "ocr" in {t.name for t in tools}


@pytest.mark.asyncio
async def test_ocr_tool_describes_src() -> None:
    tools = await server.mcp.list_tools()
    tool = next(t for t in tools if t.name == "ocr")
    schema = tool.inputSchema
    assert "src" in schema["properties"]
    assert "src" in schema.get("required", [])


def test_ocr_missing_source_raises() -> None:
    from src.ocr_convert import OcrError

    with pytest.raises(OcrError):
        server.ocr("/nonexistent/scan.pdf")
