"""멀티소스 배선: active_sources 선택 + index_all/has_new_data 가 codex+claude 를 함께 색인."""
from __future__ import annotations

import json
import os

import numpy as np

from vestige import config
from vestige.indexer import has_new_data, index_all
from vestige.sources import active_sources, enabled_source_names
from vestige.store import ArchiveDB
from vestige.vectorindex import VectorIndex

SID = "019e80dc-1754-7422-b72f-2d176635efb2"


class FakeEmbedder:
    model_name = "fake"

    def embed_passages(self, texts, parallel=None):
        return np.array([[float(len(t) % 7) + 1] * 8 for t in texts], dtype=np.float32)


def _claude_file(root):
    d = root / "proj"
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"type": "user", "uuid": "u0", "parentUuid": None, "sessionId": "claude-s1",
                    "cwd": "/c/proj", "timestamp": "2026-08-21T00:00:00Z",
                    "message": {"role": "user", "content": "클로드 질문 상세 내용입니다"}}),
        json.dumps({"type": "assistant", "sessionId": "claude-s1",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "클로드 답변"}]}}),
    ]
    (d / "claude-s1.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def _codex_file(root):
    d = root / "2026" / "08" / "21"
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        f'{{"timestamp":"t","type":"session_meta","payload":{{"id":"{SID}","cwd":"/x/proj","cli_version":"0.149.0"}}}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"user_message","message":"코덱스 질문 상세 내용입니다"}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"agent_message","message":"코덱스 답변"}}',
    ]
    (d / f"rollout-2026-08-21T10-00-00-{SID}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _wire(monkeypatch, tmp_path, sources_env=""):
    claude_root = tmp_path / "claude"
    codex_root = tmp_path / "codex"
    monkeypatch.setattr(config, "PROJECTS_DIR", claude_root)
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", codex_root)
    monkeypatch.setattr(config, "SOURCES_ENV", sources_env)
    return claude_root, codex_root


def test_active_sources_filters_by_root_existence(monkeypatch, tmp_path):
    claude_root, codex_root = _wire(monkeypatch, tmp_path)
    # 아직 폴더 없음 → 아무 소스도 활성 아님.
    assert active_sources() == []
    _claude_file(claude_root)
    names = [n for n, _a, _r in active_sources()]
    # subagent 루트 = PROJECTS_DIR(claude_root) 라 claude 루트가 생기면 함께 활성. codex 루트는 아직 없음.
    assert set(names) == {"claude-code", "subagent"}
    _codex_file(codex_root)
    names = [n for n, _a, _r in active_sources()]
    assert set(names) == {"claude-code", "codex", "subagent"}


def test_enabled_source_names_env_override(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, sources_env="claude-code")
    assert enabled_source_names() == ["claude-code"]
    monkeypatch.setattr(config, "SOURCES_ENV", "codex, claude-code")
    assert set(enabled_source_names()) == {"codex", "claude-code"}
    monkeypatch.setattr(config, "SOURCES_ENV", "bogus")   # 미등록은 무시
    assert enabled_source_names() == []


def test_index_all_covers_both_sources(monkeypatch, tmp_path):
    claude_root, codex_root = _wire(monkeypatch, tmp_path)
    _claude_file(claude_root)
    _codex_file(codex_root)
    # 방금 쓴 파일은 '진행중'으로 보여 마지막 턴이 보류된다 → mtime 을 과거로 돌려 세션 종료 간주.
    old = 1_000_000_000
    for root in (claude_root, codex_root):
        for p in root.rglob("*.jsonl"):
            os.utime(p, (old, old))
    db = ArchiveDB(tmp_path / "a.db")
    vi = VectorIndex(tmp_path / "v.npy", tmp_path / "ids.json")

    total = index_all(db, vi, FakeEmbedder(), log_fn=lambda *_: None)
    assert total == 2   # claude 1턴 + codex 1턴

    rows = db.conn.execute("SELECT session_id, project, question FROM turns ORDER BY session_id").fetchall()
    sids = {r["session_id"] for r in rows}
    assert "claude-s1" in sids
    assert SID in sids                       # codex 세션 id(파일 첫 줄 meta)에서
    projects = {r["project"] for r in rows}
    assert {"/c/proj", "/x/proj"} <= projects


def test_has_new_data_multisource(monkeypatch, tmp_path):
    claude_root, codex_root = _wire(monkeypatch, tmp_path)
    db = ArchiveDB(tmp_path / "a.db")
    assert has_new_data(db) is False         # 아직 아무 파일 없음
    _codex_file(codex_root)                   # codex 만 생겨도 True
    assert has_new_data(db) is True
