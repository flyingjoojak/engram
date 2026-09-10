"""청커 단위 테스트."""

from __future__ import annotations

from vestige.chunker import chunk_turn
from vestige.models import Action, Turn


def _turn(question="", answer="", actions=()):
    return Turn(
        id="s1:u1", session_id="s1", uuid="u1", parent_uuid=None,
        timestamp="t", project="p", question=question, answer=answer, actions=actions,
    )


def test_short_turn_single_chunk():
    chunks = chunk_turn(_turn("짧은 질문", "짧은 답변"))
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].turn_id == "s1:u1"
    assert "짧은 질문" in chunks[0].text


def test_empty_turn_no_chunk():
    assert chunk_turn(_turn("", "")) == []


def test_long_turn_splits_with_parent_id():
    long_answer = "\n\n".join(f"문단 번호 {i} 내용이 길게 이어집니다." * 5 for i in range(40))
    chunks = chunk_turn(_turn("질문", long_answer), max_chars=300, overlap=40)
    assert len(chunks) > 1
    assert all(c.turn_id == "s1:u1" for c in chunks)          # 부모 링크 유지
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # 오버랩 제외 각 조각이 상한 근처 이하인지(경계분할 기준).
    assert all(len(c.text) <= 300 + 40 for c in chunks)


def test_hard_cut_when_no_separator():
    chunks = chunk_turn(_turn("q", "가" * 1000), max_chars=200, overlap=0)
    assert len(chunks) >= 5


def test_action_included_in_embed_text():
    t = _turn("작업 요청", "완료", actions=(Action("Edit", "parse.py"),))
    chunks = chunk_turn(t)
    assert "actions" in chunks[0].text
    assert "parse.py" in chunks[0].text
