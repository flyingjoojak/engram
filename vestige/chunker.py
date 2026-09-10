"""턴 → 청크. 턴이 짧으면 1턴=1청크, 길면 경계 우선 분할 + overlap.

부모-자식: 청크는 turn_id(부모)를 들고 있어, 검색이 청크에 걸려도 반환은 턴 전체.
문자 기반 근사 분할 — 임베더가 모델 상한에서 다시 잘라주므로 안전망이 있다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS, MAX_EMBED_CHARS
from .models import Turn

# 경계 우선순위: 문단 → 줄 → 문장 → 어절 → 문자.
_SEPARATORS = ["\n\n", "\n", ". ", "。", "! ", "? ", "? ", " ", ""]


@dataclass(frozen=True)
class Chunk:
    turn_id: str  # 부모 턴
    index: int
    text: str


def _split_recursive(text: str, max_chars: int, seps: list[str]) -> list[str]:
    """세퍼레이터를 순서대로 시도하며 max_chars 이하 조각으로 나눈다."""
    if len(text) <= max_chars:
        return [text]
    sep = seps[0] if seps else ""
    rest = seps[1:] if len(seps) > 1 else [""]
    if sep == "":
        # 더 쪼갤 경계가 없음 → 하드 컷.
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    parts = text.split(sep)
    pieces: list[str] = []
    buf = ""
    for part in parts:
        candidate = part if not buf else buf + sep + part
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            pieces.append(buf)
        if len(part) > max_chars:
            pieces.extend(_split_recursive(part, max_chars, rest))
            buf = ""
        else:
            buf = part
    if buf:
        pieces.append(buf)
    return pieces


def _apply_overlap(pieces: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or len(pieces) <= 1:
        return pieces
    out = [pieces[0]]
    for prev, cur in zip(pieces, pieces[1:]):
        tail = prev[-overlap:]
        out.append(tail + cur)
    return out


def chunk_turn(
    turn: Turn,
    max_chars: int = CHUNK_MAX_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
    max_embed_chars: int = MAX_EMBED_CHARS,
) -> list[Chunk]:
    text = turn.embed_text()
    if not text.strip():
        return []
    if len(text) > max_embed_chars:  # 거대 턴은 대표분량만 임베딩(원문은 아카이브에 전량)
        text = text[:max_embed_chars]
    if len(text) <= max_chars:
        return [Chunk(turn.id, 0, text)]
    pieces = _split_recursive(text, max_chars, _SEPARATORS)
    pieces = _apply_overlap(pieces, overlap)
    return [Chunk(turn.id, i, p) for i, p in enumerate(pieces)]
