"""백필 등 장시간 작업 중 시스템 절전 방지(모니터는 꺼져도 됨).

Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
 - 시스템 sleep만 막고 디스플레이 절전은 허용(모니터 꺼도 OK).
 - 프로세스 종료 시 자동 해제 → 영구 전원설정 변경 아님.
다른 OS에서는 no-op.
"""

from __future__ import annotations

import contextlib
import sys

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def _set(flags: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        return True
    except Exception:
        return False


def prevent_sleep() -> bool:
    """시스템 절전 방지 시작. 성공 시 True."""
    return _set(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)


def allow_sleep() -> None:
    """절전 방지 해제(정상 전원 동작 복귀)."""
    _set(_ES_CONTINUOUS)


@contextlib.contextmanager
def keep_system_awake():
    ok = prevent_sleep()
    try:
        yield ok
    finally:
        if ok:
            allow_sleep()
