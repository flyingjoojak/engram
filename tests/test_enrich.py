"""정제 순수함수 테스트 (claude -p 호출 없이 파싱·프롬프트만)."""

from __future__ import annotations

import vestige.enrich as enrich
from vestige.enrich import _build_prompt, _parse_json, resolve_claude_bin
from vestige.models import Turn


def _turn(tid, q="질문", a="답변"):
    return Turn(id=tid, session_id="s1", uuid=tid, parent_uuid=None,
                timestamp="t", project="p", question=q, answer=a, actions=())


def test_parse_plain_json():
    out = '{"turns":[{"id":"s1:u1","summary":"요약","tags":["a","b"]}]}'
    items = _parse_json(out)
    assert items[0]["id"] == "s1:u1"
    assert items[0]["tags"] == ["a", "b"]


def test_parse_code_fenced():
    out = '```json\n{"turns":[{"id":"x","summary":"s","tags":[]}]}\n```'
    assert _parse_json(out)[0]["id"] == "x"


def test_parse_with_surrounding_text():
    out = '네, 정리했습니다:\n{"turns":[{"id":"y","summary":"s","tags":["t"]}]}\n끝.'
    assert _parse_json(out)[0]["id"] == "y"


def test_parse_non_dict_returns_empty():
    assert _parse_json("[1,2,3]") == []


def test_build_prompt_contains_ids_and_content():
    p = _build_prompt([_turn("s1:u1", "청킹 질문"), _turn("s1:u2", "임베딩 질문")])
    assert "id=s1:u1" in p
    assert "id=s1:u2" in p
    assert "청킹 질문" in p
    assert "JSON" in p


# --- 백엔드 플러그블 ----------------------------------------------------
def test_resolve_model_defaults():
    from vestige.enrich import _resolve_model
    assert _resolve_model("claude", None) == "sonnet"
    assert _resolve_model("anthropic", None) == "claude-sonnet-5"
    assert _resolve_model("openai", None) == "gpt-4o-mini"
    assert _resolve_model("gemini", None) == "gemini-2.0-flash"
    assert _resolve_model("ollama", None) == "llama3.1"
    assert _resolve_model("claude", "custom-model") == "custom-model"


def test_backend_available_off():
    from vestige.enrich import backend_available
    ok, why = backend_available("off")
    assert ok is False
    assert "off" in why.lower()


def test_generate_dispatch(monkeypatch):
    import pytest
    from vestige import enrich
    monkeypatch.setattr(enrich, "_call_claude_cli", lambda p, m, **k: f"cli:{m}")
    monkeypatch.setattr(enrich, "_call_anthropic_api", lambda p, m, **k: f"api:{m}")
    monkeypatch.setattr(enrich, "_call_openai_compatible",
                        lambda p, m, base_url, api_key, **k: f"oai:{m}@{base_url}")
    assert enrich._generate("x", "claude", "sonnet") == "cli:sonnet"
    assert enrich._generate("x", "anthropic", "claude-sonnet-5") == "api:claude-sonnet-5"
    assert enrich._generate("x", "openai", "gpt-4o-mini") == "oai:gpt-4o-mini@None"
    # gemini는 Google OpenAI호환 엔드포인트로 라우팅
    assert "generativelanguage.googleapis.com" in enrich._generate("x", "gemini", "gemini-2.0-flash")
    # ollama는 로컬 base_url
    assert "11434" in enrich._generate("x", "ollama", "llama3.1")
    with pytest.raises(RuntimeError):
        enrich._generate("x", "off", "m")


# --- claude 실행파일 해석(PATH 미상속 GUI 앱 대응) ------------------------
def test_resolve_claude_bin_prefers_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("VESTIGE_CLAUDE_BIN", str(fake))
    # PATH/표준경로를 못 찾게 막아도 override 가 우선.
    monkeypatch.setattr(enrich.shutil, "which", lambda _n: None)
    monkeypatch.setattr(enrich, "_claude_search_dirs", lambda: [])
    assert resolve_claude_bin() == str(fake)


def test_resolve_claude_bin_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("VESTIGE_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(enrich.shutil, "which", lambda n: "/usr/bin/claude" if n == "claude" else None)
    assert resolve_claude_bin() == "/usr/bin/claude"


def test_resolve_claude_bin_scans_standard_dirs_when_path_misses(monkeypatch, tmp_path):
    # GUI 앱: PATH 에 없지만 표준 설치 위치(예: /opt/homebrew/bin)에 있으면 찾아야 한다.
    monkeypatch.delenv("VESTIGE_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(enrich.shutil, "which", lambda _n: None)   # PATH 미상속 흉내
    brew = tmp_path / "opt_homebrew_bin"
    brew.mkdir()
    binname = "claude.exe" if enrich.os.name == "nt" else "claude"   # 호스트 규칙에 맞춘 파일명
    (brew / binname).write_text("#!/bin/sh\n")
    monkeypatch.setattr(enrich, "_claude_search_dirs", lambda: [str(brew)])
    assert resolve_claude_bin() == str(brew / binname)


def test_resolve_claude_bin_none_when_absent(monkeypatch):
    monkeypatch.delenv("VESTIGE_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(enrich.shutil, "which", lambda _n: None)
    monkeypatch.setattr(enrich, "_claude_search_dirs", lambda: [])
    assert resolve_claude_bin() is None


def test_claude_env_prepends_bindir_to_path(monkeypatch):
    from pathlib import Path
    monkeypatch.setenv("PATH", "/existing")
    bin_path = "/opt/homebrew/bin/claude"
    env = enrich._claude_env(bin_path)
    parts = env["PATH"].split(enrich.os.pathsep)
    assert parts[0] == str(Path(bin_path).parent)   # 실행파일 폴더가 PATH 맨 앞(node 등 해석용)
    assert "/opt/homebrew/bin" in parts and "/usr/local/bin" in parts   # 표준 bin 도 포함
    assert "/existing" in parts                     # 기존 PATH 보존
