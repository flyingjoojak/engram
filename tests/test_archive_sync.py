"""아카이브 export/import — 텍스트만 옮겨 없는 세션을 병합(벡터 제외)."""

from __future__ import annotations

from types import SimpleNamespace

from vestige import archive_sync as A
from vestige.models import Turn
from vestige.store import ArchiveDB


def _turn(tid: str, sid: str, q: str, a: str) -> Turn:
    return Turn(id=tid, session_id=sid, uuid=tid, parent_uuid="", timestamp="2026-01-01T00:00",
                project="proj", question=q, answer=a, actions=())


def _seed(db: ArchiveDB, tid: str, sid: str, chunks: list[str], summary: str | None = None) -> None:
    db.upsert_turn(_turn(tid, sid, f"q-{tid}", f"a-{tid}"))
    db.add_chunks([SimpleNamespace(turn_id=tid, index=i, text=t) for i, t in enumerate(chunks)])
    if summary:
        db.set_enrichment(tid, summary, ["tag1", "tag2"])
    db.commit()


def test_export_import_roundtrip(tmp_path):
    proj = tmp_path / "projects"
    proj.mkdir()
    src = ArchiveDB(tmp_path / "a.db")
    _seed(src, "t1", "s1", ["c-a", "c-b"], summary="요약1")
    _seed(src, "t2", "s2", ["c-c"])
    n = A.export_archive(src, proj, "devA")
    assert n == 2
    assert (proj / A.ARCHIVE_DIRNAME / "devA.ndjson").exists()

    dst = ArchiveDB(tmp_path / "b.db")
    added = A.import_archives(dst, proj, "devB")
    assert added == 2
    assert dst.conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 2
    assert dst.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 3
    # 정제(summary/tags)도 함께 이동
    s, tags = dst.get_enrichment("t1")
    assert s == "요약1" and tags == ["tag1", "tag2"]
    # 키워드(FTS) 인덱스도 채워짐 → 검색 가능
    assert dst.conn.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0] == 2


def test_import_skips_existing_and_own(tmp_path):
    proj = tmp_path / "projects"
    proj.mkdir()
    src = ArchiveDB(tmp_path / "a.db")
    _seed(src, "t1", "s1", ["x"])
    _seed(src, "t2", "s2", ["y"])
    A.export_archive(src, proj, "devA")

    dst = ArchiveDB(tmp_path / "b.db")
    _seed(dst, "t1", "s1", ["x"])          # t1 이미 있음
    added = A.import_archives(dst, proj, "devB")
    assert added == 1                      # t2만 새로
    # 자기 자신 export는 건너뜀
    A.export_archive(dst, proj, "devB")
    assert A.import_archives(dst, proj, "devB") == 0


def test_import_no_dir(tmp_path):
    dst = ArchiveDB(tmp_path / "b.db")
    assert A.import_archives(dst, tmp_path / "nope", "devB") == 0
