"""가치 필터(2단계): 아카이브엔 남기되 임베딩에서 뺄지 판정.

원칙: 행동 있으면 무조건 임베딩(작업턴 보호). 행동 없고 알맹이도 없는
명백한 잡담만 스킵. 보수적 편향(애매하면 임베딩) — 놓침이 노이즈보다 나쁨.
"""

from __future__ import annotations

from .config import MIN_EMBED_CHARS
from .models import Turn

# 명백한 사소어(정확히 일치할 때만).
_TRIVIAL = {
    "ok", "okay", "ㅇㅇ", "ㅇ", "응", "넵", "네", "예", "고마워", "고맙습니다",
    "감사", "감사합니다", "ㄱㅅ", "thanks", "thx", "yes", "no", "y", "n",
}


def should_embed(turn: Turn, min_chars: int = MIN_EMBED_CHARS) -> bool:
    """임베딩(검색 대상) 여부. False여도 아카이브·스레드엔 남는다."""
    if turn.actions:
        return True
    q = turn.question.strip()
    a = turn.answer.strip()
    if q.lower() in _TRIVIAL and len(a) < min_chars:
        return False
    if len(q) + len(a) < min_chars:
        return False
    return True
