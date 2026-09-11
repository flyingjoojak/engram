"""재개 시 CLI 폴더 신뢰 pre-seed(#181) — 비파괴·멱등·실패시 폴백."""
from __future__ import annotations

import json
import os

from vestige import resume_trust as R


def _trusted(projects: dict, cwd: str) -> bool:
    """cwd 와 같은 폴더로 정규화 매칭되는 신뢰(true) 항목이 하나라도 있으면 True."""
    return any(
        isinstance(e, dict) and e.get("hasTrustDialogAccepted") is True and R._norm(k) == R._norm(cwd)
        for k, e in projects.items()
    )


# ── Claude Code (~/.claude.json) ──────────────────────────────────
def test_claude_sets_trust_and_preserves(tmp_path):
    cwd = tmp_path / "proj"
    cwd.mkdir()
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({
        "someTopLevel": 123,
        "projects": {
            str(cwd): {"hasTrustDialogAccepted": False, "allowedTools": ["x"]},
            "/home/me/other": {"hasTrustDialogAccepted": True},
        },
    }), encoding="utf-8")
    assert R.pretrust_claude(str(cwd), path=p) is True
    d = json.loads(p.read_text(encoding="utf-8"))
    assert _trusted(d["projects"], str(cwd))
    assert d["projects"][str(cwd)]["hasTrustDialogAccepted"] is True
    assert d["projects"][str(cwd)]["allowedTools"] == ["x"]           # 다른 키 보존
    assert d["projects"]["/home/me/other"]["hasTrustDialogAccepted"] is True  # 남의 항목 불변
    assert d["someTopLevel"] == 123                                    # 최상위 보존


def test_claude_creates_entry_when_missing(tmp_path):
    cwd = tmp_path / "newproj"
    cwd.mkdir()
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"projects": {"/a": {"hasTrustDialogAccepted": True}}}), encoding="utf-8")
    assert R.pretrust_claude(str(cwd), path=p) is True
    d = json.loads(p.read_text(encoding="utf-8"))
    assert _trusted(d["projects"], str(cwd))
    assert d["projects"]["/a"]["hasTrustDialogAccepted"] is True       # 기존 보존


def test_claude_trusts_existing_variant_slash(tmp_path):
    # claude 가 어느 표기를 읽든 매칭되도록, 슬래시만 다른 기존 항목도 신뢰로 바뀌어야 함(핵심 버그).
    cwd = tmp_path / "proj"
    cwd.mkdir()
    other_fmt = str(cwd).replace("\\", "/") if os.name == "nt" else str(cwd) + "/"
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"projects": {other_fmt: {"hasTrustDialogAccepted": False}}}), encoding="utf-8")
    assert R.pretrust_claude(str(cwd), path=p) is True
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["projects"][other_fmt]["hasTrustDialogAccepted"] is True  # 표기만 다른 기존 항목도 신뢰로


def test_claude_ensures_native_backslash_key_on_windows(tmp_path):
    # 윈도우: 네이티브 백슬래시 키가 반드시 신뢰로 존재해야 함(claude 가 읽는 표기).
    cwd = tmp_path / "proj"
    cwd.mkdir()
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    assert R.pretrust_claude(str(cwd), path=p) is True
    d = json.loads(p.read_text(encoding="utf-8"))
    if os.name == "nt":
        native = str(cwd)  # tmp_path 는 네이티브(백슬래시)
        assert d["projects"].get(native, {}).get("hasTrustDialogAccepted") is True
        assert d["projects"].get(native.replace("\\", "/"), {}).get("hasTrustDialogAccepted") is True
    else:
        assert d["projects"].get(str(cwd), {}).get("hasTrustDialogAccepted") is True


def test_claude_idempotent(tmp_path):
    cwd = tmp_path / "proj"
    cwd.mkdir()
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    assert R.pretrust_claude(str(cwd), path=p) is True
    first = p.read_text(encoding="utf-8")
    assert R.pretrust_claude(str(cwd), path=p) is True   # 두 번째 호출
    assert p.read_text(encoding="utf-8") == first        # 멱등: 이미 다 신뢰라 재기록 없음


def test_claude_missing_file_returns_false(tmp_path):
    assert R.pretrust_claude("/home/me/proj", path=tmp_path / "nope.json") is False


def test_claude_bad_json_returns_false(tmp_path):
    p = tmp_path / ".claude.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert R.pretrust_claude("/home/me/proj", path=p) is False


# ── Codex (~/.codex/config.toml) ──────────────────────────────────
def test_codex_appends_section_when_absent(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('model = "gpt-5"\n[projects.\'/other\']\ntrust_level = "trusted"\n', encoding="utf-8")
    assert R.pretrust_codex("/home/me/proj", path=p) is True
    text = p.read_text(encoding="utf-8")
    assert 'model = "gpt-5"' in text                                 # 기존 보존
    assert "[projects.'/home/me/proj']" in text
    assert text.count("[projects.") == 2                             # 새 섹션 1개 추가
    assert 'trust_level = "trusted"' in text.split("[projects.'/home/me/proj']")[1]


def test_codex_existing_section_not_duplicated(tmp_path):
    p = tmp_path / "config.toml"
    orig = "[projects.'/home/me/proj']\ntrust_level = \"trusted\"\n"
    p.write_text(orig, encoding="utf-8")
    assert R.pretrust_codex("/home/me/proj", path=p) is True
    assert p.read_text(encoding="utf-8") == orig                     # 중복 추가 안 함, 그대로


def test_codex_creates_file_when_missing(tmp_path):
    p = tmp_path / ".codex" / "config.toml"
    assert R.pretrust_codex("/home/me/proj", path=p) is True
    text = p.read_text(encoding="utf-8")
    assert "[projects.'/home/me/proj']" in text and 'trust_level = "trusted"' in text


# ── pretrust 라우팅/가드 ──────────────────────────────────────────
def test_pretrust_skips_path_with_single_quote(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(R, "pretrust_claude", lambda *a, **k: called.append("c") or True)
    assert R.pretrust("claude-code", "/home/me/o'brien") is False
    assert called == []                                             # 작은따옴표 경로는 건너뜀


def test_pretrust_routes_by_source(monkeypatch):
    monkeypatch.setattr(R, "pretrust_codex", lambda cwd, path=None: "CODEX")
    monkeypatch.setattr(R, "pretrust_claude", lambda cwd, path=None: "CLAUDE")
    assert R.pretrust("codex", "/p") == "CODEX"
    assert R.pretrust("claude-code", "/p") == "CLAUDE"
