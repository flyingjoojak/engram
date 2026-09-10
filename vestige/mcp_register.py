"""MCP 서버(vestige-mcp)를 여러 MCP 클라이언트 설정에 등록/해제.

지원 대상(각자 형식이 달라 개별 처리):
- Claude Code    : `claude mcp add` CLI (-s user)
- Claude Desktop : JSON  (%APPDATA%/Claude/claude_desktop_config.json 등) → mcpServers
- Codex CLI      : TOML  (~/.codex/config.toml)                          → [mcp_servers.<name>]
- Gemini CLI     : JSON  (~/.gemini/settings.json)                        → mcpServers

파일 수정 전 항상 `<파일>.bak` 백업. 손상된(파싱 실패) 설정은 건드리지 않고 오류 반환.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "vestige"


def mcp_command() -> tuple[str, list[str]]:
    """클라이언트가 실행할 커맨드.

    - 패키지(frozen) exe: 자기 자신을 `--mcp` 인자로 실행(별도 설치·python 불필요).
      frozen에선 `-m vestige.mcp_server`가 동작하지 않으므로 이 경로가 유일하다.
    - 개발: 콘솔스크립트(vestige-mcp)가 있으면 그 절대경로, 없으면 `python -m`.
    """
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp"]
    exe = shutil.which("vestige-mcp")
    if exe:
        return exe, []
    return sys.executable, ["-m", "vestige.mcp_server"]


def _desktop_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


CODEX_PATH = Path.home() / ".codex" / "config.toml"
GEMINI_PATH = Path.home() / ".gemini" / "settings.json"


def _backup_and_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ── JSON (Claude Desktop, Gemini) ─────────────────────────────────────
def _json_load(path: Path):
    if path.exists() and path.stat().st_size:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None   # 손상 → 편집 거부 신호
    return {}


def _json_registered(path: Path) -> bool:
    data = _json_load(path)
    return bool(data) and NAME in (data.get("mcpServers") or {})


def _json_register(path: Path) -> None:
    data = _json_load(path)
    if data is None:
        raise ValueError(f"{path} 파싱 실패 — 직접 확인 필요")
    cmd, args = mcp_command()
    data.setdefault("mcpServers", {})[NAME] = {"command": cmd, "args": args}
    _backup_and_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _json_unregister(path: Path) -> None:
    data = _json_load(path)
    if not data:
        return
    servers = data.get("mcpServers")
    if isinstance(servers, dict) and NAME in servers:
        del servers[NAME]
        _backup_and_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ── TOML (Codex CLI) — 섹션 블록 단위 추가/삭제 ────────────────────────
_HDR = re.compile(r'\s*\[mcp_servers\.(?:%s|"%s")(?:\..*)?\]\s*$' % (re.escape(NAME), re.escape(NAME)))


def _toml_registered() -> bool:
    if not CODEX_PATH.exists():
        return False
    return any(_HDR.match(ln) for ln in CODEX_PATH.read_text(encoding="utf-8").splitlines())


def _toml_register() -> None:
    text = CODEX_PATH.read_text(encoding="utf-8") if CODEX_PATH.exists() else ""
    if any(_HDR.match(ln) for ln in text.splitlines()):
        return   # 이미 등록됨
    cmd, args = mcp_command()
    block = (f'[mcp_servers."{NAME}"]\n'
             f'command = {json.dumps(cmd)}\n'
             f'args = {json.dumps(args)}\n')
    prefix = (text.rstrip() + "\n\n") if text.strip() else ""
    _backup_and_write(CODEX_PATH, prefix + block)


def _toml_unregister() -> None:
    if not CODEX_PATH.exists():
        return
    lines = CODEX_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    out, skip = [], False
    for ln in lines:
        if _HDR.match(ln):        # 우리 섹션(및 하위테이블) 시작 → 건너뜀
            skip = True
            continue
        if skip and re.match(r'\s*\[', ln) and not _HDR.match(ln):
            skip = False          # 다른 섹션 시작 → 스킵 종료
        if not skip:
            out.append(ln)
    _backup_and_write(CODEX_PATH, "".join(out))


# ── Claude Code (CLI) ─────────────────────────────────────────────────
def _claude() -> str | None:
    return shutil.which("claude")


# Windows 한국어 로케일(cp949)이 claude의 UTF-8/이모지 출력을 못 읽는 문제 → UTF-8 고정.
_RUN = dict(capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # windowed exe에서 콘솔 창 억제


def _cc_registered() -> bool:
    """user 스코프 등록 여부를 **설정 파일을 직접 읽어** 판정.

    `claude mcp list`는 각 서버에 헬스체크(핑)를 돌려 느리고(수 초~타임아웃), 타임아웃 시
    예외가 나 '미등록'으로 오탐한다 → 등록해도 '등록'으로 보이는 버그. `claude mcp add -s user`가
    쓰는 ~/.claude.json 의 최상위 mcpServers 를 읽으면 즉시·정확하다.
    """
    for p in (Path.home() / ".claude.json", Path.home() / ".claude" / "settings.json"):
        try:
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                if NAME in (d.get("mcpServers") or {}):
                    return True
        except Exception:  # noqa: BLE001 — 손상/부분기록 파일은 건너뜀
            continue
    return False


def _cc_register() -> None:
    exe = _claude()
    if not exe:
        raise ValueError("claude CLI를 찾을 수 없음 — 표시된 명령을 직접 실행하세요")
    cmd, args = mcp_command()
    subprocess.run([exe, "mcp", "remove", NAME, "-s", "user"], timeout=12, **_RUN)
    r = subprocess.run([exe, "mcp", "add", NAME, "-s", "user", "--", cmd, *args], timeout=20, **_RUN)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout or "claude mcp add 실패").strip()[:300])


def _cc_unregister() -> None:
    exe = _claude()
    if not exe:
        return
    subprocess.run([exe, "mcp", "remove", NAME, "-s", "user"], timeout=12, **_RUN)


# ── 공개 API ──────────────────────────────────────────────────────────
def snippets() -> dict:
    cmd, args = mcp_command()
    full = (cmd + (" " + " ".join(args) if args else "")).strip()
    return {
        "claude-code": f"claude mcp add {NAME} -s user -- {full}",
        "json": json.dumps({"mcpServers": {NAME: {"command": cmd, "args": args}}}, indent=2, ensure_ascii=False),
        "toml": f'[mcp_servers."{NAME}"]\ncommand = {json.dumps(cmd)}\nargs = {json.dumps(args)}',
    }


def targets() -> list[dict]:
    dp = _desktop_path()
    sn = snippets()
    return [
        {"id": "claude-code", "label": "Claude Code", "method": "cli",
         "installed": _claude() is not None, "registered": _cc_registered(),
         "path": "claude CLI (user scope)", "snippet": sn["claude-code"]},
        {"id": "claude-desktop", "label": "Claude Desktop", "method": "json",
         "installed": dp.parent.exists(), "registered": _json_registered(dp),
         "path": str(dp), "snippet": sn["json"]},
        {"id": "codex-cli", "label": "Codex CLI", "method": "toml",
         "installed": CODEX_PATH.exists(), "registered": _toml_registered(),
         "path": str(CODEX_PATH), "snippet": sn["toml"]},
        {"id": "gemini-cli", "label": "Gemini CLI", "method": "json",
         "installed": GEMINI_PATH.exists(), "registered": _json_registered(GEMINI_PATH),
         "path": str(GEMINI_PATH), "snippet": sn["json"]},
    ]


_REG = {
    "claude-code": (_cc_register, _cc_unregister),
    "claude-desktop": (lambda: _json_register(_desktop_path()), lambda: _json_unregister(_desktop_path())),
    "codex-cli": (_toml_register, _toml_unregister),
    "gemini-cli": (lambda: _json_register(GEMINI_PATH), lambda: _json_unregister(GEMINI_PATH)),
}


def register(target_id: str) -> None:
    if target_id not in _REG:
        raise ValueError(f"알 수 없는 대상: {target_id}")
    _REG[target_id][0]()


def unregister(target_id: str) -> None:
    if target_id not in _REG:
        raise ValueError(f"알 수 없는 대상: {target_id}")
    _REG[target_id][1]()
