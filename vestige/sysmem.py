"""가용 물리 메모리 조회(Windows). 다른 OS/실패 시 None → 메모리 가드 비활성."""

from __future__ import annotations

import sys


def _query():
    """(total_mb, avail_mb) 또는 None. Windows 외/실패 시 None → 가드 비활성."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        mb = 1024 * 1024
        return int(stat.ullTotalPhys // mb), int(stat.ullAvailPhys // mb)
    except Exception:
        return None


def available_mb() -> int | None:
    q = _query()
    return q[1] if q else None


def total_mb() -> int | None:
    q = _query()
    return q[0] if q else None


def set_low_priority() -> bool:
    """이 프로세스를 낮은 우선순위로 → 포그라운드 작업에 CPU 양보. Windows 전용."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        _BELOW_NORMAL = 0x00004000
        k = ctypes.windll.kernel32
        return bool(k.SetPriorityClass(k.GetCurrentProcess(), _BELOW_NORMAL))
    except Exception:
        return False
