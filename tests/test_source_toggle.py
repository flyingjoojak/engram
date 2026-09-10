"""색인 소스 on/off 토글: sources_disabled meta 가 enabled_source_names 에서 제외되는지."""
from vestige import config, store
from vestige.sources import (disabled_sources, enabled_source_names, is_substream,
                             parent_source, toggleable_source_names)


def _db(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "a.db")   # ArchiveDB() 기본 경로를 tmp 로
    return store.ArchiveDB(tmp_path / "a.db")


def test_disabled_sources_reads_meta(monkeypatch, tmp_path):
    db = _db(monkeypatch, tmp_path)
    assert disabled_sources() == set()          # 기본: 아무것도 안 껐음
    db.set_meta("sources_disabled", "codex"); db.commit()
    assert disabled_sources() == {"codex"}


def test_enabled_excludes_disabled_default(monkeypatch, tmp_path):
    db = _db(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SOURCES_ENV", "")
    db.set_meta("sources_disabled", "codex"); db.commit()
    names = enabled_source_names()
    assert "codex" not in names and "claude-code" in names
    db.set_meta("sources_disabled", ""); db.commit()
    # subagent(배경 에이전트) 어댑터도 기본 등록 소스 → 세 개 다 활성.
    assert set(enabled_source_names()) == {"claude-code", "codex", "subagent"}


def test_enabled_excludes_disabled_with_env_pin(monkeypatch, tmp_path):
    db = _db(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SOURCES_ENV", "claude-code,codex")
    db.set_meta("sources_disabled", "codex"); db.commit()
    assert enabled_source_names() == ["claude-code"]


def test_subagent_is_substream_of_claude_code():
    # subagent 는 하위 스트림(source_name="claude-code") → 부모 출처로 접힌다.
    assert is_substream("subagent") and parent_source("subagent") == "claude-code"
    assert not is_substream("claude-code") and not is_substream("codex")


def test_subagent_follows_parent_toggle(monkeypatch, tmp_path):
    # claude-code 를 끄면 하위 스트림 subagent 도 함께 색인에서 빠져야 한다(부모를 따름).
    db = _db(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SOURCES_ENV", "")
    db.set_meta("sources_disabled", "claude-code"); db.commit()
    names = set(enabled_source_names())
    assert "claude-code" not in names and "subagent" not in names   # 부모 끄면 하위도 빠짐
    assert "codex" in names                                          # 무관한 소스는 유지


def test_subagent_not_in_toggleable_list():
    # 설정 UI 에 노출되는 토글 목록엔 하위 스트림이 없다(부모 토글만).
    toggd = toggleable_source_names()
    assert "subagent" not in toggd
    assert "claude-code" in toggd and "codex" in toggd
