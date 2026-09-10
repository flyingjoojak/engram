"""count_pending 단위 테스트 — 모델 로드 없이 stat+커서 비교 로직만."""

from __future__ import annotations

import json
import os
import time

from vestige.indexer import count_pending, iter_jsonl


class _FakeDB:
    """get_cursor(path) -> (offset, size, mtime)만 흉내내는 최소 스텁."""

    def __init__(self, offsets: dict[str, int]):
        self._offsets = offsets

    def get_cursor(self, path: str):
        return (self._offsets.get(path, 0), 0, 0.0)


def _make(tmp_path, name: str, size: int) -> str:
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return str(p)


def test_empty_dir_returns_zeros(tmp_path):
    assert count_pending(_FakeDB({}), tmp_path) == {
        "new_sessions": 0, "updated_sessions": 0, "files": 0
    }


def test_missing_dir_returns_zeros(tmp_path):
    assert count_pending(_FakeDB({}), tmp_path / "nope")["files"] == 0


def test_new_updated_and_done_classification(tmp_path):
    fresh = _make(tmp_path, "fresh.jsonl", 100)     # 커서 없음 → 새 대화
    partial = _make(tmp_path, "partial.jsonl", 100)  # 0 < offset < size → 갱신
    done = _make(tmp_path, "done.jsonl", 100)        # offset == size → 대기 아님
    db = _FakeDB({partial: 40, done: 100})
    r = count_pending(db, tmp_path)
    assert r == {"new_sessions": 1, "updated_sessions": 1, "files": 2}
    # fresh는 커서가 없어 new로만 잡히고, done은 어디에도 안 들어감
    assert fresh not in (partial, done)


def test_iter_jsonl_excludes_stversions(tmp_path):
    live = tmp_path / "proj" / "live.jsonl"
    live.parent.mkdir(parents=True)
    live.write_text("x")
    ver = tmp_path / "proj" / ".stversions" / "old~1.jsonl"   # Syncthing 버전 백업
    ver.parent.mkdir(parents=True)
    ver.write_text("x")
    found = {p.name for p in iter_jsonl(tmp_path)}
    assert found == {"live.jsonl"}   # .stversions 백업본은 제외


def test_count_pending_ignores_stversions(tmp_path):
    _make(tmp_path, "live.jsonl", 100)               # 새 대화 1
    stv = tmp_path / ".stversions"
    stv.mkdir()
    (stv / "backup.jsonl").write_bytes(b"x" * 100)    # 버전 백업 — 세면 안 됨
    r = count_pending(_FakeDB({}), tmp_path)
    assert r == {"new_sessions": 1, "updated_sessions": 0, "files": 1}


def _write_turns(path, n: int) -> str:
    """실제 Claude Code JSONL 포맷(테스트 픽스처와 동일) n턴 작성."""
    lines = []
    for i in range(n):
        lines.append(json.dumps({
            "type": "user", "uuid": f"u{i}", "parentUuid": None, "sessionId": "s1",
            "cwd": "C:/p", "timestamp": f"2026-08-26T00:0{i}:00Z",
            "message": {"role": "user", "content": f"질문 {i}"},
        }))
        lines.append(json.dumps({
            "type": "assistant", "sessionId": "s1",
            "message": {"role": "assistant", "content": [{"type": "text", "text": f"답 {i}"}]},
        }))
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return str(path)


def test_active_session_single_inprogress_turn_not_pending(tmp_path):
    # 활성(방금 수정) 세션에 진행 중 턴 하나뿐 → index_file이 홀드백 → 지금 색인 대상 아님 → 대기 아님(최신).
    f = _write_turns(tmp_path / "s1.jsonl", 1)
    assert count_pending(_FakeDB({}), tmp_path)["files"] == 0
    # 같은 파일이 idle(오래 전 수정)이면 전량 색인 대상 → 대기 1.
    old = time.time() - 10 * 60
    os.utime(f, (old, old))
    assert count_pending(_FakeDB({}), tmp_path)["files"] == 1


def test_active_session_completed_turn_is_pending(tmp_path):
    # 활성 세션에 완결 턴 + 진행 중 턴 → 완결 턴은 지금 색인 가능 → 대기 1.
    _write_turns(tmp_path / "s2.jsonl", 2)
    assert count_pending(_FakeDB({}), tmp_path)["files"] == 1
