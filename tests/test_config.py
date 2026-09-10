"""설정 파일 로더 테스트 (KEY=VALUE → 환경변수, 실제 환경변수 우선)."""

from __future__ import annotations

from vestige.config import _load_config_file


def test_load_sets_missing_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("VESTIGE_TEST_KEY", raising=False)
    f = tmp_path / "config.env"
    f.write_text('VESTIGE_TEST_KEY=hello\n# 주석\n\nOTHER="quoted val"\n', encoding="utf-8")
    _load_config_file(f)
    import os
    assert os.environ["VESTIGE_TEST_KEY"] == "hello"
    assert os.environ["OTHER"] == "quoted val"


def test_real_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTIGE_TEST_KEY2", "from-env")
    f = tmp_path / "config.env"
    f.write_text("VESTIGE_TEST_KEY2=from-file\n", encoding="utf-8")
    _load_config_file(f)
    import os
    assert os.environ["VESTIGE_TEST_KEY2"] == "from-env"  # setdefault → 환경변수 우선


def test_missing_file_is_noop(tmp_path):
    _load_config_file(tmp_path / "nope.env")  # 예외 없이 조용히 통과


def test_write_config_creates_and_updates(tmp_path, monkeypatch):
    from vestige import config as C
    f = tmp_path / "config.env"
    monkeypatch.setattr(C, "CONFIG_PATH", f)

    C.write_config({"VESTIGE_ENRICH_BACKEND": "openai", "OPENAI_API_KEY": "sk-x"})
    body = f.read_text(encoding="utf-8")
    assert "VESTIGE_ENRICH_BACKEND=openai" in body
    assert "OPENAI_API_KEY=sk-x" in body

    # 기존 값 교체 + 주석/기타 줄 보존
    f.write_text("# 내 메모\nVESTIGE_ENRICH_BACKEND=openai\nFOO=bar\n", encoding="utf-8")
    C.write_config({"VESTIGE_ENRICH_BACKEND": "gemini"})
    body = f.read_text(encoding="utf-8")
    assert "# 내 메모" in body and "FOO=bar" in body
    assert "VESTIGE_ENRICH_BACKEND=gemini" in body
    assert "openai" not in body  # 이전 값 사라짐

    # 빈 값 = 비활성(주석 처리)
    C.write_config({"FOO": ""})
    assert "#FOO=" in f.read_text(encoding="utf-8")
