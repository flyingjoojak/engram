"""세션 동기화 충돌 리졸버 단위 테스트 (Phase 1 / M1).

superset-wins / fork 판정과 파일 적용을 전송(Syncthing) 없이 검증.
"""

from __future__ import annotations

from pathlib import Path

from vestige.session_sync import (
    ConflictOutcome,
    base_for_conflict,
    classify,
    find_session_file,
    resolve_all,
    resolve_conflict_file,
    session_activity,
    sync_tick,
)


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8")
    return path


# ── classify: 순수 판정 ──────────────────────────────────────────────

def test_classify_identical():
    assert classify(["a", "b"], ["a", "b"]) == "identical"


def test_classify_conflict_wins_when_base_is_prefix():
    # base ⊂ conflict → conflict가 최신 상위집합
    assert classify(["a", "b"], ["a", "b", "c"]) == "conflict_wins"


def test_classify_base_wins_when_conflict_is_prefix():
    assert classify(["a", "b", "c"], ["a", "b"]) == "base_wins"


def test_classify_fork_when_diverged():
    # 같은 지점 이후 다른 내용 → 진짜 분기
    assert classify(["a", "b", "x"], ["a", "b", "y"]) == "fork"


def test_classify_empty_base_is_prefix_of_anything():
    assert classify([], ["a"]) == "conflict_wins"
    assert classify([], []) == "identical"


# ── base_for_conflict: 충돌 파일명 파싱 ──────────────────────────────

def test_base_for_conflict_parses_syncthing_name():
    cf = Path("/x/proj/abc-123.sync-conflict-20260101-120000-ABC123.jsonl")
    assert base_for_conflict(cf) == Path("/x/proj/abc-123.jsonl")


def test_base_for_conflict_none_for_normal_file():
    assert base_for_conflict(Path("/x/proj/abc-123.jsonl")) is None


# ── resolve_conflict_file: 파일 적용 ─────────────────────────────────

def _mk(tmp_path: Path, base_lines, conflict_lines):
    base = _write(tmp_path / "sess.jsonl", base_lines)
    conflict = _write(
        tmp_path / "sess.sync-conflict-20260101-120000-ABC123.jsonl", conflict_lines
    )
    return base, conflict


def test_resolve_conflict_wins_replaces_base_and_removes_conflict(tmp_path):
    base, conflict = _mk(tmp_path, ["a", "b"], ["a", "b", "c"])
    out = resolve_conflict_file(base, conflict)
    assert out.resolution == "conflict_wins"
    assert base.read_text(encoding="utf-8").splitlines() == ["a", "b", "c"]
    assert not conflict.exists()
    assert out.forked_to is None


def test_resolve_base_wins_keeps_base_and_removes_conflict(tmp_path):
    base, conflict = _mk(tmp_path, ["a", "b", "c"], ["a", "b"])
    out = resolve_conflict_file(base, conflict)
    assert out.resolution == "base_wins"
    assert base.read_text(encoding="utf-8").splitlines() == ["a", "b", "c"]
    assert not conflict.exists()


def test_resolve_identical_removes_conflict(tmp_path):
    base, conflict = _mk(tmp_path, ["a", "b"], ["a", "b"])
    out = resolve_conflict_file(base, conflict)
    assert out.resolution == "identical"
    assert not conflict.exists()
    assert base.exists()


def test_resolve_fork_preserves_both_under_new_id(tmp_path):
    base, conflict = _mk(tmp_path, ["a", "b", "x"], ["a", "b", "y"])
    out = resolve_conflict_file(base, conflict, new_id="newid-9999")
    assert out.resolution == "fork"
    # 원본은 그대로
    assert base.read_text(encoding="utf-8").splitlines() == ["a", "b", "x"]
    # 분기본은 새 세션 파일로 보존
    fork = tmp_path / "newid-9999.jsonl"
    assert out.forked_to == str(fork)
    assert fork.read_text(encoding="utf-8").splitlines() == ["a", "b", "y"]
    assert not conflict.exists()   # 충돌본은 fork 파일로 rename됨


def test_resolve_missing_base_promotes_conflict(tmp_path):
    conflict = _write(
        tmp_path / "sess.sync-conflict-20260101-120000-ABC123.jsonl", ["a", "b"]
    )
    base = tmp_path / "sess.jsonl"   # 존재하지 않음
    out = resolve_conflict_file(base, conflict)
    assert out.resolution == "conflict_wins"
    assert base.read_text(encoding="utf-8").splitlines() == ["a", "b"]
    assert not conflict.exists()


# ── resolve_all: 디렉터리 스캔 드라이버 ──────────────────────────────

def test_resolve_all_scans_and_resolves(tmp_path):
    proj = tmp_path / "C--Users-alice"
    proj.mkdir()
    _write(proj / "sess.jsonl", ["a", "b"])
    _write(proj / "sess.sync-conflict-20260101-120000-ABC123.jsonl", ["a", "b", "c"])
    # 충돌 없는 다른 세션은 건드리지 않음
    _write(proj / "other.jsonl", ["z"])

    outcomes = resolve_all(tmp_path)
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], ConflictOutcome)
    assert outcomes[0].resolution == "conflict_wins"
    assert (proj / "sess.jsonl").read_text(encoding="utf-8").splitlines() == ["a", "b", "c"]
    assert (proj / "other.jsonl").exists()
    assert not list(proj.glob("*.sync-conflict-*"))


# ── sync_tick: M2 데몬 한 틱 ─────────────────────────────────────────

def test_sync_tick_resolves_without_index(tmp_path):
    _write(tmp_path / "s.jsonl", ["a"])
    _write(tmp_path / "s.sync-conflict-20260101-120000-ABC123.jsonl", ["a", "b"])
    res = sync_tick(tmp_path)
    assert len(res.outcomes) == 1
    assert res.outcomes[0].resolution == "conflict_wins"
    assert res.indexed is False   # index_fn 미주입 → 색인 안 함
    assert (tmp_path / "s.jsonl").read_text(encoding="utf-8").splitlines() == ["a", "b"]


def test_sync_tick_calls_index_fn_after_resolving(tmp_path):
    _write(tmp_path / "s.jsonl", ["a", "b"])
    calls: list[int] = []

    def index_fn() -> bool:
        calls.append(1)
        return True

    res = sync_tick(tmp_path, index_fn=index_fn)
    assert calls == [1]
    assert res.indexed is True


def test_sync_tick_index_fn_error_is_swallowed(tmp_path):
    _write(tmp_path / "s.jsonl", ["a"])

    def bad_index() -> bool:
        raise RuntimeError("boom")

    res = sync_tick(tmp_path, index_fn=bad_index)
    assert res.indexed is False   # 색인 실패가 데몬을 죽이지 않음


# ── M3: 활성 세션 가드 ───────────────────────────────────────────────

def test_session_activity_recent_is_active(tmp_path):
    f = _write(tmp_path / "s.jsonl", ["a"])
    mtime = f.stat().st_mtime
    # 수정 10초 뒤 기준 → window(300) 안 → active
    act = session_activity(f, now=mtime + 10, window=300)
    assert act.active is True
    assert 9 < act.seconds_since < 11


def test_session_activity_stale_is_inactive(tmp_path):
    f = _write(tmp_path / "s.jsonl", ["a"])
    mtime = f.stat().st_mtime
    # 수정 600초 뒤 기준 → window(300) 밖 → 비활성
    act = session_activity(f, now=mtime + 600, window=300)
    assert act.active is False


def test_session_activity_missing_file(tmp_path):
    act = session_activity(tmp_path / "nope.jsonl")
    assert act.active is False
    assert act.seconds_since is None


def test_find_session_file_locates_across_subfolders(tmp_path):
    proj = tmp_path / "C--Users-alice"
    proj.mkdir()
    target = _write(proj / "abc-123.jsonl", ["x"])
    assert find_session_file("abc-123", root=tmp_path) == target
    assert find_session_file("does-not-exist", root=tmp_path) is None
