"""소스 어댑터 레지스트리·인터페이스·발견 로직."""
from pathlib import Path

from vestige.sources import ADAPTERS, SourceAdapter, default_adapter


def test_default_is_claude_code():
    a = default_adapter()
    assert a.name == "claude-code"
    assert "claude-code" in ADAPTERS


def test_default_satisfies_protocol():
    assert isinstance(default_adapter(), SourceAdapter)


def test_discover_finds_jsonl_and_skips_backups(tmp_path: Path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "a.jsonl").write_text("{}\n", encoding="utf-8")
    # 버전 백업/아카이브 폴더는 제외돼야 함
    (tmp_path / ".stversions").mkdir()
    (tmp_path / ".stversions" / "old.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / ".vestige-archive").mkdir()
    (tmp_path / ".vestige-archive" / "dev.jsonl").write_text("{}\n", encoding="utf-8")
    # 레거시 아카이브 폴더도 계속 제외돼야 함(back-compat)
    (tmp_path / ".chatmem-archive").mkdir()
    (tmp_path / ".chatmem-archive" / "old.jsonl").write_text("{}\n", encoding="utf-8")

    found = {p.name for p in default_adapter().discover(tmp_path)}
    assert found == {"a.jsonl"}
