"""배치 실행 로그: 언제/무엇을 처리했는지 한 줄씩 기록 → 정상동작 신뢰·문제 조기발견."""

from __future__ import annotations

import time

from .config import LOG_PATH


def batch_log(msg: str) -> None:
    # 로깅 실패(파일 잠금·권한 등)가 파이프라인을 죽이면 안 됨 → 조용히 무시.
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts}  {msg}\n")
    except Exception:
        pass
