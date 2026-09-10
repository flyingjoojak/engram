"""드리프트 자동 감지(_update_drift): 새 데이터인데 0턴이면 감지, 턴 나오면 해제."""
from vestige import config, store
from vestige.indexer import _update_drift

SID = "019e80dc-1754-7422-b72f-2d176635efb2"


def _broken_codex_root(tmp_path):
    root = tmp_path / "codex"
    d = root / "2026" / "08" / "24"
    d.mkdir(parents=True)
    lines = [f'{{"timestamp":"t","type":"session_meta","payload":{{"id":"{SID}","cwd":"/x","cli_version":"0.200.0"}}}}']
    for i in range(8):  # 어댑터가 모르는 새 이벤트만(=포맷 변경) → 턴 0개
        lines.append('{"timestamp":"t","type":"event_msg","payload":{"type":"brand_new_event","blob":"x' + str(i) + '"}}')
    (d / f"rollout-2026-08-24T10-00-00-{SID}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_drift_flag_set_then_cleared(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "a.db")
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", _broken_codex_root(tmp_path))
    db = store.ArchiveDB(tmp_path / "a.db")

    # 새 바이트 있었는데 0턴 → 확정 후 플래그 세팅
    _update_drift(db, {"codex": 0}, {"codex": 1})
    assert db.get_meta("drift_sources") == "codex"

    # 다시 턴이 나옴(형식 지원 후) → 회복으로 플래그 해제
    _update_drift(db, {"codex": 3}, {"codex": 1})
    assert (db.get_meta("drift_sources") or "") == ""


def test_no_drift_when_turns_extracted(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "a.db")
    db = store.ArchiveDB(tmp_path / "a.db")
    _update_drift(db, {"codex": 5}, {"codex": 2})   # 턴이 나오면 감지 안 함
    assert (db.get_meta("drift_sources") or "") == ""


def test_no_drift_when_no_new_data(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "a.db")
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", _broken_codex_root(tmp_path))
    db = store.ArchiveDB(tmp_path / "a.db")
    _update_drift(db, {"codex": 0}, {"codex": 0})   # 새 데이터 없으면(0턴이어도) 감지 안 함
    assert (db.get_meta("drift_sources") or "") == ""
