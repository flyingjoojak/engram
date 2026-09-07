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
import logging
import os
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 이 프로세스가 락을 쥐고 있는 동안의 카운트. is_locked()는 "다른 프로세스"를 판정하는 용도이지만,
# OS 어드바이저리 락은 fd 단위라 같은 프로세스가 다른 fd로 재시도하면 실패(=잡힘)로 나온다.
# 그래서 호출측이 '자기 프로세스 보유분'을 제외할 수 있도록 held_here()를 제공한다.
_held_lock = threading.Lock()
_held_count = 0


def held_here() -> bool:
    """이 프로세스가 지금 색인 락을 쥐고 있는지."""
    with _held_lock:
        return _held_count > 0


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
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)   # 잠근 오프셋(0)과 맞춤 — PID 기록으로 이동한 위치 보정
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError as ex:                  # 실패해도 이어지는 close()가 핸들 단위로 락을 해제
        logger.debug("색인 락 해제 실패(무해, close가 대신 해제): %r", ex)


class IndexLock:
    """크로스-프로세스 색인 락. acquire()로 얻고 release()로 푼다. 컨텍스트매니저로도 쓴다."""

    def __init__(self) -> None:
        self._fd: int | None = None

    def acquire(self) -> bool:
        p = _lock_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as ex:
            # 락 파일을 못 열면(권한·읽기전용·디스크풀 등) 락 없이 판정할 수 없다. 호출측은 acquire 실패를
            # "다른 프로세스 색인 중"으로 해석해 건너뛰므로, 이 드문 실패가 조용히 묻히지 않게 반드시 로깅한다.
            logger.warning("색인 락 파일 열기 실패(%s) — 색인 건너뜀으로 처리됨: %r", p, ex)
            return False
        if not _try_lock_fd(fd):
            os.close(fd)
            return False                      # 정상 경합: 다른 (프로세스의) fd가 이미 쥠
        self._fd = fd
        with contextlib.suppress(OSError):   # 홀더 PID 기록(디버깅용, 락 자체는 fd가 담당)
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
            os.lseek(fd, 0, os.SEEK_SET)     # 잠근 오프셋(0)로 복귀 — release의 언락 오프셋 일치
        global _held_count
        with _held_lock:
            _held_count += 1
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        _unlock_fd(self._fd)
        with contextlib.suppress(OSError):
            os.close(self._fd)
        self._fd = None
        global _held_count
        with _held_lock:
            _held_count = max(0, _held_count - 1)

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
