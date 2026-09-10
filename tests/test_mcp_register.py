"""mcp_command() 경로 선택 — 패키지(frozen) exe vs 개발 환경."""

from __future__ import annotations

from vestige import mcp_register as R


def test_frozen_registers_self_with_mcp_flag(monkeypatch):
    # 패키지 exe: 자기 자신을 `--mcp`로 실행(별도 설치 불필요).
    monkeypatch.setattr(R.sys, "frozen", True, raising=False)
    monkeypatch.setattr(R.sys, "executable", r"C:\app\vestige-backend.exe", raising=False)
    cmd, args = R.mcp_command()
    assert cmd == r"C:\app\vestige-backend.exe"
    assert args == ["--mcp"]


def test_dev_prefers_console_script(monkeypatch):
    monkeypatch.setattr(R.sys, "frozen", False, raising=False)
    monkeypatch.setattr(R.shutil, "which", lambda name: "/usr/local/bin/vestige-mcp")
    cmd, args = R.mcp_command()
    assert cmd == "/usr/local/bin/vestige-mcp"
    assert args == []


def test_dev_falls_back_to_python_module(monkeypatch):
    monkeypatch.setattr(R.sys, "frozen", False, raising=False)
    monkeypatch.setattr(R.shutil, "which", lambda name: None)   # 콘솔스크립트 없음
    monkeypatch.setattr(R.sys, "executable", "/usr/bin/python", raising=False)
    cmd, args = R.mcp_command()
    assert cmd == "/usr/bin/python"
    assert args == ["-m", "vestige.mcp_server"]
