"""색인 크로스-프로세스 락 테스트.

같은 프로세스에서 두 번째 획득이 거부되는지(=다른 프로세스가 잡으면 못 얻는지)와,
is_locked() 판정, 해제 후 재획득을 확인한다. 실제 별도 프로세스는 subprocess 로 검증.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import engram.proclock as pl


def _point_data_dir(monkeypatch, tmp_path):
    from engram import config as C
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)


def test_second_acquire_denied_same_holder(monkeypatch, tmp_path):
    _point_data_dir(monkeypatch, tmp_path)
    a = pl.IndexLock()
    assert a.acquire() is True
    try:
        b = pl.IndexLock()
        assert b.acquire() is False       # 이미 잡혀 있으면 두 번째는 실패
        assert pl.is_locked() is True     # 잡힌 상태로 판정
    finally:
        a.release()


def test_release_allows_reacquire(monkeypatch, tmp_path):
    _point_data_dir(monkeypatch, tmp_path)
    a = pl.IndexLock()
    assert a.acquire() is True
    a.release()
    assert pl.is_locked() is False        # 풀린 뒤엔 안 잡힘
    b = pl.IndexLock()
    assert b.acquire() is True            # 다시 획득 가능
    b.release()


def test_context_manager(monkeypatch, tmp_path):
    _point_data_dir(monkeypatch, tmp_path)
    with pl.IndexLock() as got:
        assert got is True
        assert pl.is_locked() is True
    assert pl.is_locked() is False        # __exit__ 에서 해제


def test_cross_process_mutual_exclusion(monkeypatch, tmp_path):
    """실제 별도 프로세스가 락을 쥔 동안 이 프로세스가 못 얻는지 확인."""
    _point_data_dir(monkeypatch, tmp_path)
    ready = tmp_path / "ready.flag"
    goahead = tmp_path / "go.flag"
    code = textwrap.dedent(f"""
        import os, time
        from pathlib import Path
        from engram import config as C
        C.DATA_DIR = Path({str(tmp_path)!r})
        import engram.proclock as pl
        lk = pl.IndexLock()
        assert lk.acquire()
        open({str(ready)!r}, "w").close()          # 잡았다고 신호
        while not os.path.exists({str(goahead)!r}): # 부모가 검사 끝낼 때까지 홀드
            time.sleep(0.02)
        lk.release()
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=os.getcwd())
    try:
        for _ in range(200):
            if ready.exists():
                break
            __import__("time").sleep(0.02)
        assert ready.exists(), "자식이 락을 못 잡음"
        assert pl.is_locked() is True             # 다른 프로세스가 쥔 걸 감지
        assert pl.IndexLock().acquire() is False  # 이 프로세스는 못 얻음
    finally:
        goahead.write_text("go")
        proc.wait(timeout=10)
    assert pl.is_locked() is False                # 자식 해제 후엔 풀림
