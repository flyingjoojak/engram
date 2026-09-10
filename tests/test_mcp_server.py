"""MCP 서버 오프로드 검증 — 동기 툴 블로킹을 워커 스레드로 뺐는지."""

from __future__ import annotations

import asyncio
import threading
import time

from vestige import mcp_server as M


def test_tools_are_async():
    # 툴이 async여야 FastMCP가 이벤트 루프를 안 막고 await한다.
    for fn in (M.search_memory, M.get_session, M.recent_sessions, M.stats):
        assert asyncio.iscoroutinefunction(fn), f"{fn.__name__} must be async"


def test_offload_uses_single_non_main_worker():
    async def go():
        main = threading.get_ident()
        a, b = await asyncio.gather(
            M._offload(threading.get_ident),
            M._offload(threading.get_ident),
        )
        assert a == b            # 항상 동일한 단일 워커(sqlite 연결이 한 스레드에 고정됨)
        assert a != main         # 이벤트 루프(메인) 스레드가 아님
    asyncio.run(go())


def test_event_loop_not_blocked_during_offload():
    async def go():
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(100):
                ticks += 1
                await asyncio.sleep(0.005)

        t = asyncio.create_task(ticker())
        await asyncio.sleep(0)          # ticker가 먼저 한 번 돌게 양보
        await M._offload(lambda: time.sleep(0.2))   # 워커에서 0.2s 블록
        during = ticks
        t.cancel()
        # 루프가 안 막혔다면 0.2s 동안 ticker가 여러 번 진행(≈수십 회). 막혔다면 1 이하.
        assert during > 5, f"event loop appears blocked (ticks={during})"
    asyncio.run(go())
