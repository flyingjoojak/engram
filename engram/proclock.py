"""색인 크로스-프로세스 락.

여러 프로세스가 동시에 같은 archive.db 를 색인하지 않게 OS 파일락으로 상호배제한다.
- 웹(Electron 셸) 인-프로세스 자동/수동 색인·재색인
- OS 스케줄러가 띄운 별도 프로세스의 `engram index`

OS 어드바이저리 락이라 프로세스가 죽어도 커널이 자동 해제 → 스테일 락 파일 문제 없음.
스레드 단위 상호배제(web.py 의 _index_lock)는 같은 프로세스 안에서만 유효하므로, 프로세스
경계를 넘는 보호는 이 모듈이 담당한다.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path


def _lock_path() -> Path:
    from . import config as C
    return C.DATA_DIR / "index.lock"


def _try_lock_fd(fd: int) -> bool:
    """비차단으로 fd에 배타 락 시도. 성공 True, 이미 잡혀 있으면 False."""
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock_fd(fd: int) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


class IndexLock:
    """크로스-프로세스 색인 락. acquire()로 얻고 release()로 푼다. 컨텍스트매니저로도 쓴다."""

    def __init__(self) -> None:
        self._fd: int | None = None

    def acquire(self) -> bool:
        p = _lock_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return False   # 락 파일조차 못 열면(권한 등) 색인은 진행(락 없이) — 안전 실패
        if not _try_lock_fd(fd):
            os.close(fd)
            return False
        self._fd = fd
        with contextlib.suppress(OSError):   # 홀더 PID 기록(디버깅용, 락 자체는 fd가 담당)
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        _unlock_fd(self._fd)
        with contextlib.suppress(OSError):
            os.close(self._fd)
        self._fd = None

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()


def is_locked() -> bool:
    """다른 곳에서 색인 락을 잡고 있는지 비차단 시도로 판정.

    주의: 같은 프로세스가 다른 fd로 이미 락을 쥐고 있어도 True 로 나올 수 있다(OS 어드바이저리
    락은 fd 단위). 그래서 호출측은 '자기 프로세스가 색인 중이 아님'을 먼저 확인한 뒤(idle 일 때만)
    이 함수로 '다른 프로세스가 색인 중'인지 판정해야 한다.
    """
    lk = IndexLock()
    if lk.acquire():
        lk.release()
        return False
    return True
