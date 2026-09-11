"""재개 시 CLI 폴더 신뢰 pre-seed(#181) — 비파괴·멱등·실패시 폴백."""
from __future__ import annotations

import json

from vestige import resume_trust as R


# ── Claude Code (~/.claude.json) ──────────────────────────────────
def test_claude_sets_trust_on_existing_untrusted_entry(tmp_path):
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({
        "someTopLevel": 123,
        "projects": {
            "/home/me/proj": {"hasTrustDialogAccepted": False, "allowedTools": ["x"]},
            "/home/me/other": {"hasTrustDialogAccepted": True},
        },
    }), encoding="utf-8")
    assert R.pretrust_claude("/home/me/proj", path=p) is True
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["projects"]["/home/me/proj"]["hasTrustDialogAccepted"] is True
    assert d["projects"]["/home/me/proj"]["allowedTools"] == ["x"]   # 다른 키 보존
    assert d["projects"]["/home/me/other"]["hasTrustDialogAccepted"] is True  # 남의 항목 불변
    assert d["someTopLevel"] == 123                                   # 최상위 보존


def test_claude_creates_entry_when_missing(tmp_path):
    # 실재 폴더를 cwd 로(윈도우 resolve() 가 드라이브 없는 경로에 드라이브를 붙이는 아티팩트 회피).
    cwd = tmp_path / "newproj"
    cwd.mkdir()
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"projects": {"/a": {"hasTrustDialogAccepted": True}}}), encoding="utf-8")
    assert R.pretrust_claude(str(cwd), path=p) is True
    d = json.loads(p.read_text(encoding="utf-8"))
    # 생성된 항목을 정규화 매칭으로 찾음(플랫폼별 키 표기 차이 흡수).
    key = next(k for k in d["projects"] if R._norm(k) == R._norm(str(cwd)))
    assert d["projects"][key]["hasTrustDialogAccepted"] is True
    assert d["projects"]["/a"]["hasTrustDialogAccepted"] is True     # 기존 보존


def test_claude_matches_trailing_slash(tmp_path):
    # 저장된 키와 cwd 가 trailing slash 만 다를 때 같은 폴더로 인식(중복 항목 생성 안 함).
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"projects": {"/home/me/proj/": {"hasTrustDialogAccepted": False}}}), encoding="utf-8")
    assert R.pretrust_claude("/home/me/proj", path=p) is True
    d = json.loads(p.read_text(encoding="utf-8"))
    assert list(d["projects"].keys()) == ["/home/me/proj/"]          # 새 키 안 생김
    assert d["projects"]["/home/me/proj/"]["hasTrustDialogAccepted"] is True


def test_claude_already_trusted_is_noop_true(tmp_path):
    p = tmp_path / ".claude.json"
    orig = json.dumps({"projects": {"/home/me/proj": {"hasTrustDialogAccepted": True}}})
    p.write_text(orig, encoding="utf-8")
    assert R.pretrust_claude("/home/me/proj", path=p) is True
    assert p.read_text(encoding="utf-8") == orig                     # 파일 그대로


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
