"""인덱서(파일 단위 증분·체크포인트·재개) 테스트. 가짜 임베더로 fastembed 없이."""

from __future__ import annotations

import json

import numpy as np

from vestige.indexer import has_new_data, index_file
from vestige.store import ArchiveDB
from vestige.vectorindex import VectorIndex


class FakeEmbedder:
    model_name = "fake"

    def embed_passages(self, texts):
        # 결정적 8차원 벡터(정규화 불필요 — 테스트용).
        return np.array([[float(len(t) % 7) + 1] * 8 for t in texts], dtype=np.float32)


def _write_jsonl(path, n_turns):
    lines = []
    for i in range(n_turns):
        lines.append(json.dumps({
            "type": "user", "uuid": f"u{i}", "parentUuid": None, "sessionId": "s1",
            "cwd": "C:/proj", "timestamp": f"2026-07-24T00:0{i}:00Z",
            "message": {"role": "user", "content": f"질문 번호 {i} 입니다 상세 내용"},
        }))
        lines.append(json.dumps({
            "type": "assistant", "sessionId": "s1",
            "message": {"role": "assistant", "content": [{"type": "text", "text": f"답변 {i}"}]},
        }))
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def test_index_file_basic(tmp_path):
    f = tmp_path / "s1.jsonl"
    _write_jsonl(f, 3)
    db = ArchiveDB(tmp_path / "a.db")
    vi = VectorIndex(tmp_path / "v.npy", tmp_path / "ids.json")

    n = index_file(f, db, vi, FakeEmbedder(), idle_secs=0, checkpoint_turns=1)
    assert n == 3
    assert db.conn.execute("SELECT COUNT(*) c FROM turns").fetchone()["c"] == 3
    assert len(vi) >= 3  # 턴당 최소 1청크
    # 커서가 파일 끝까지 전진했는지.
    offset, size, _ = db.get_cursor(str(f))
    assert offset == size


def test_index_file_idempotent_rerun(tmp_path):
    f = tmp_path / "s1.jsonl"
    _write_jsonl(f, 3)
    db = ArchiveDB(tmp_path / "a.db")
    vi = VectorIndex(tmp_path / "v.npy", tmp_path / "ids.json")
    e = FakeEmbedder()

    index_file(f, db, vi, e, idle_secs=0)
    v1 = len(vi)
    # 다시 돌려도 새로 처리할 게 없다(커서가 끝).
    n2 = index_file(f, db, vi, e, idle_secs=0)
    assert n2 == 0
    assert len(vi) == v1  # 중복 안 늘어남


def test_has_new_data(tmp_path, monkeypatch):
    proj = tmp_path / "projects"
    proj.mkdir()
    f = proj / "s1.jsonl"
    _write_jsonl(f, 2)
    db = ArchiveDB(tmp_path / "a.db")
    vi = VectorIndex(tmp_path / "v.npy", tmp_path / "ids.json")

    # 아직 인덱싱 전 → 새 데이터 있음.
    assert has_new_data(db, projects_dir=proj) is True

    index_file(f, db, vi, FakeEmbedder(), idle_secs=0)
    # 다 처리 후 → 새 데이터 없음(모델 로드 스킵될 상황).
    assert has_new_data(db, projects_dir=proj) is False

    # 대화가 이어져 파일이 커지면 → 다시 새 데이터 있음.
    with open(f, "ab") as fh:
        import json as _j
        fh.write((_j.dumps({"type": "user", "uuid": "u9", "sessionId": "s1",
                            "message": {"role": "user", "content": "새 질문 추가됨 상세"}}) + "\n").encode())
    assert has_new_data(db, projects_dir=proj) is True


def test_index_file_resume_from_cursor(tmp_path):
    f = tmp_path / "s1.jsonl"
    _write_jsonl(f, 4)
    db = ArchiveDB(tmp_path / "a.db")
    vi = VectorIndex(tmp_path / "v.npy", tmp_path / "ids.json")
    e = FakeEmbedder()

    # 1턴만 처리되도록 인위적으로 끊는 대신, 전체 처리 후 커서 리셋해 재개 검증.
    index_file(f, db, vi, e, idle_secs=0)
    # 커서를 0으로 되돌리고 재실행 → 멱등(같은 턴 수, 벡터 중복 없음).
    db.set_cursor(str(f), 0, 0, 0.0)
    db.commit()
    before = len(vi)
    index_file(f, db, vi, e, idle_secs=0)
    assert db.conn.execute("SELECT COUNT(*) c FROM turns").fetchone()["c"] == 4
    assert len(vi) == before  # 재처리해도 키가 같아 교체(중복 X)


def _turn(session, uuid, text, ts="2026-07-24T00:00:00Z"):
    return json.dumps({"type": "user", "uuid": uuid, "parentUuid": None, "sessionId": session,
                       "cwd": "C:/proj", "timestamp": ts,
                       "message": {"role": "user", "content": text}})


def _assistant(session, text, tool=None):
    content = [{"type": "text", "text": text}]
    if tool:
        content.append({"type": "tool_use", "name": tool, "input": {"command": "run"}})
    return json.dumps({"type": "assistant", "sessionId": session,
                       "message": {"role": "assistant", "content": content}})


def test_idle_finalized_turn_recaptures_trailing_content(tmp_path):
    """긴 도구호출로 idle 확정된 턴에 나중에 붙은 뒷내용이 유실되지 않고 합쳐지는지(회귀)."""
    import os, time
    f = tmp_path / "s.jsonl"
    db = ArchiveDB(tmp_path / "a.db")
    vi = VectorIndex(tmp_path / "v.npy", tmp_path / "v.json")
    emb = FakeEmbedder()

    # 1) 유저 + 어시스턴트(텍스트 + 도구호출, tool_result 아직 없음), 파일 idle.
    f.write_bytes(("\n".join([
        _turn("s1", "u1", "빌드를 고쳐줘 상세 내용입니다"),
        _assistant("s1", "빌드를 확인하겠습니다.", tool="Bash"),
    ]) + "\n").encode("utf-8"))
    old = time.time() - 300
    os.utime(f, (old, old))
    index_file(str(f), db, vi, emb, idle_secs=120)
    t1 = db.get_turn("s1:u1")
    assert t1 is not None and t1.answer == "빌드를 확인하겠습니다."
    assert db.get_hold(str(f)) is not None   # 열린 턴 시작이 기록됨

    # 2) 도구 완료 → 같은 턴에 뒷내용 추가(새 유저턴 없음).
    with open(f, "a", encoding="utf-8") as fp:
        fp.write(_assistant("s1", "빌드 완료. 이제 테스트를 돌리겠습니다.") + "\n")
    os.utime(f, (old, old))
    index_file(str(f), db, vi, emb, idle_secs=120)
    t2 = db.get_turn("s1:u1")
    assert "빌드 완료" in (t2.answer or ""), "idle 확정 턴의 뒷내용이 유실됨"

    # 3) 변화 없으면 스킵(무의미한 재처리 없음).
    assert index_file(str(f), db, vi, emb, idle_secs=120) == 0
