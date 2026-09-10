"""MCP 서버 도구 등록/유틸 테스트 (임베더·실데이터 없이)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")

from vestige import mcp_server as M  # noqa: E402


def test_tools_registered():
    tools = asyncio.run(M.mcp.list_tools())
    names = {t.name for t in tools}
    assert {"search_memory", "get_session", "recent_sessions", "stats"} <= names


def test_kst_format():
    assert M._kst("2026-07-22T06:35:00Z") == "2026-07-22 15:35"   # UTC→KST(+9)
    assert M._kst("") == ""
