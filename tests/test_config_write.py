"""write_config: 개행 주입 차단(설정 화이트리스트 우회 방지) + 정상 저장."""
import pytest

from vestige import config


def test_write_config_rejects_newline(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.env")
    with pytest.raises(ValueError):
        config.write_config({"CODEX_SESSIONS_DIR": "C:/x\nVESTIGE_ENRICH_BACKEND=off"})
    with pytest.raises(ValueError):
        config.write_config({"CLAUDE_PROJECTS_DIR": "a\rb"})
    assert not (tmp_path / "config.env").exists()   # 거부 시 파일도 안 씀


def test_write_config_normal_value(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.env")
    config.write_config({"CODEX_SESSIONS_DIR": "C:/Users/me/.codex/sessions"})
    text = (tmp_path / "config.env").read_text(encoding="utf-8")
    assert "CODEX_SESSIONS_DIR=C:/Users/me/.codex/sessions" in text
    assert "VESTIGE_ENRICH_BACKEND=off" not in text
