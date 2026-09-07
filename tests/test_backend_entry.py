"""프리즈 사이드카 진입점(backend_entry) 인자 디스패치 테스트.

회귀 대상: 스케줄러가 `engram-backend.exe -m engram index` 로 작업을 등록하는데,
프리즈 exe가 이 인자를 무시하고 웹서버를 띄워 '웹이 혼자 열리던' 버그.
이제 `-m engram <cmd>` 는 웹서버가 아니라 engram.cli 로 넘어가야 한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ENTRY = Path(__file__).resolve().parent.parent / "packaging" / "backend_entry.py"


def _load_entry():
    spec = importlib.util.spec_from_file_location("backend_entry", _ENTRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dash_m_engram_index_routes_to_cli(monkeypatch):
    entry = _load_entry()
    seen = {}

    def fake_cli_main(argv=None):
        seen["argv"] = argv
        return 0

    import engram.cli as cli
    monkeypatch.setattr(cli, "main", fake_cli_main)
    monkeypatch.setattr("sys.argv", ["engram-backend.exe", "-m", "engram", "index"])

    with pytest.raises(SystemExit) as ex:
        entry.main()
    assert ex.value.code == 0
    assert seen["argv"] == ["index"]        # 웹서버 아님 — CLI 로 index 실행


def test_dash_m_engram_sync_once_preserves_flags(monkeypatch):
    entry = _load_entry()
    seen = {}
    import engram.cli as cli
    monkeypatch.setattr(cli, "main", lambda argv=None: seen.setdefault("argv", argv) or 0)
    monkeypatch.setattr("sys.argv", ["engram-backend.exe", "-m", "engram", "sync", "--once"])

    with pytest.raises(SystemExit):
        entry.main()
    assert seen["argv"] == ["sync", "--once"]


def test_bare_subcommand_routes_to_cli(monkeypatch):
    entry = _load_entry()
    seen = {}
    import engram.cli as cli
    monkeypatch.setattr(cli, "main", lambda argv=None: seen.setdefault("argv", argv) or 0)
    monkeypatch.setattr("sys.argv", ["engram-backend.exe", "enrich"])

    with pytest.raises(SystemExit):
        entry.main()
    assert seen["argv"] == ["enrich"]


def test_mcp_flag_routes_to_mcp_server(monkeypatch):
    entry = _load_entry()
    called = {"n": 0}
    import engram.mcp_server as mcp
    monkeypatch.setattr(mcp, "main", lambda: called.__setitem__("n", called["n"] + 1))
    monkeypatch.setattr("sys.argv", ["engram-backend.exe", "--mcp"])

    entry.main()                            # mcp 경로는 return(웹서버 안 탐)
    assert called["n"] == 1


def test_digit_port_does_not_route_to_cli(monkeypatch):
    """포트 숫자(Electron/더블클릭)는 CLI 가 아니라 웹서버 경로여야 한다."""
    entry = _load_entry()
    cli_called = {"n": 0}
    import engram.cli as cli
    monkeypatch.setattr(cli, "main", lambda argv=None: cli_called.__setitem__("n", cli_called["n"] + 1) or 0)

    captured = {}

    def fake_uvicorn_run(app, **kw):
        captured["port"] = kw.get("port")

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setattr("sys.argv", ["engram-backend.exe", "8765"])

    entry.main()
    assert cli_called["n"] == 0             # CLI 로 새지 않음
    assert captured["port"] == 8765         # 웹서버가 그 포트로 기동
