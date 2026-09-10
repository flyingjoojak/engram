"""검색 소스 필터: tool_sources로 특정 출처만 · distinct_sources 옵션 목록."""
from __future__ import annotations

import json
import os

import numpy as np

from vestige import config
from vestige.indexer import index_all
from vestige.search import search
from vestige.store import ArchiveDB
from vestige.vectorindex import VectorIndex

SID = "019e80dc-1754-7422-b72f-2d176635efb2"
KW = "공통키워드매칭"


class FakeEmbedder:
    model_name = "fake"

    def embed_passages(self, texts, parallel=None):
        return np.array([[float(len(t) % 7) + 1] * 8 for t in texts], dtype=np.float32)


def _wire(monkeypatch, tmp_path):
    claude_root, codex_root = tmp_path / "claude", tmp_path / "codex"
    (claude_root / "proj").mkdir(parents=True)
    (claude_root / "proj" / "claude-s1.jsonl").write_bytes(("\n".join([
        json.dumps({"type": "user", "uuid": "u0", "parentUuid": None, "sessionId": "claude-s1",
                    "cwd": "/c", "timestamp": "2026-08-21T00:00:00Z",
                    "message": {"role": "user", "content": f"{KW} 클로드 쪽 질문 상세"}}),
        json.dumps({"type": "assistant", "sessionId": "claude-s1",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "클로드 답변 상세"}]}}),
    ]) + "\n").encode("utf-8"))
    d = codex_root / "2026" / "08" / "21"
    d.mkdir(parents=True)
    (d / f"rollout-2026-08-21T10-00-00-{SID}.jsonl").write_text("\n".join([
        f'{{"timestamp":"t","type":"session_meta","payload":{{"id":"{SID}","cwd":"/x","cli_version":"0.149.0"}}}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"user_message","message":"' + KW + ' 코덱스 쪽 질문 상세"}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"agent_message","message":"코덱스 답변 상세"}}',
    ]) + "\n", encoding="utf-8")
    for root in (claude_root, codex_root):
        for p in root.rglob("*.jsonl"):
            os.utime(p, (1_000_000_000, 1_000_000_000))   # 세션 종료 간주(마지막 턴 확정)
    monkeypatch.setattr(config, "PROJECTS_DIR", claude_root)
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", codex_root)
    monkeypatch.setattr(config, "SOURCES_ENV", "")


def _index(tmp_path):
    db = ArchiveDB(tmp_path / "a.db")
    vi = VectorIndex(tmp_path / "v.npy", tmp_path / "ids.json")
    index_all(db, vi, FakeEmbedder(), log_fn=lambda *_: None)
    return db, vi


def test_distinct_sources(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    db, _vi = _index(tmp_path)
    srcs = dict(db.distinct_sources())
    assert srcs.get("claude-code") == 1
    assert srcs.get("codex") == 1


def test_search_filter_by_source(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    db, vi = _index(tmp_path)

    # 필터 없음 → 양쪽 다 나옴(키워드 검색, 임베더 불필요).
    allh = search(KW, db, vi, None, k=10, semantic=False, keyword=True)
    got = {h.turn.source for h in allh}
    assert got == {"claude-code", "codex"}

    # codex만 → codex 결과만.
    only_codex = search(KW, db, vi, None, k=10, semantic=False, keyword=True, tool_sources={"codex"})
    assert only_codex and all(h.turn.source == "codex" for h in only_codex)

    # claude-code만 → claude 결과만.
    only_claude = search(KW, db, vi, None, k=10, semantic=False, keyword=True, tool_sources={"claude-code"})
    assert only_claude and all(h.turn.source == "claude-code" for h in only_claude)
