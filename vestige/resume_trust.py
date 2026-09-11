"""세션 재개 시 CLI '폴더 신뢰' 프롬프트를 미리 통과시킨다(#181).

재개(`_launch_resume`)는 세션의 cwd 에서 새 터미널로 `claude --resume`/`codex resume` 를 띄운다.
CLI 가 처음 여는 폴더면 "이 폴더를 신뢰?" 프롬프트가 떠서 원클릭 재개가 막힌다. 그 폴더는
이미 그 세션이 기록해 둔 사용자 자신의 프로젝트 cwd 이므로, 재개 직전에 CLI 설정을 pre-seed 해
프롬프트 없이 바로 진입하게 한다.

원칙:
- **best-effort·비파괴·실패시 폴백**: 어떤 이유로든 실패하면 조용히 False 반환(그럼 CLI 가 원래대로
  프롬프트를 띄운다). 사용자 설정을 절대 깨지 않는다(기존 내용 보존, 원자적 교체/추가만).
- **호출자가 검증한 cwd 에만** 적용(web.api_resume 이 `_safe_resume_cwd` 로 UNC/네트워크 거부·
  실재 폴더만 통과). 임의 폴더 신뢰 금지.
- 포맷 의존(CLI 버전 변화 시 키가 바뀔 수 있음) → 실패해도 무해하도록 설계.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def pretrust(source: str, cwd: str) -> bool:
    """source 별로 cwd 를 CLI 신뢰 목록에 pre-seed. best-effort(never raises)."""
    try:
        if not cwd or "'" in cwd:   # 작은따옴표 포함 경로(희귀)는 codex 리터럴 키가 깨지므로 건너뜀
            return False
        if source == "codex":
            return pretrust_codex(cwd)
        return pretrust_claude(cwd)   # claude-code(기본)
    except Exception:  # noqa: BLE001 — 신뢰 pre-seed 실패가 재개를 막으면 안 됨
        return False


def _norm(p: str) -> str:
    """경로 비교용 정규화: 슬래시 통일 + normpath + (윈도우) 대소문자 무시."""
    return os.path.normcase(os.path.normpath(p.replace("/", os.sep)))


# ── Claude Code (~/.claude.json) ──────────────────────────────────
def pretrust_claude(cwd: str, path: Path | None = None) -> bool:
    """~/.claude.json 의 projects[<cwd>].hasTrustDialogAccepted 를 true 로(비파괴 read-modify-write)."""
    path = path or (Path.home() / ".claude.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 파일 없음/파싱 실패 → 프롬프트로 폴백
        return False
    if not isinstance(data, dict):
        return False
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
        data["projects"] = projects

    target = _norm(cwd)
    # 기존 항목을 슬래시·대소문자 차이까지 감안해 찾음(있으면 그걸 갱신 → 키 추측 불필요).
    key = next((k for k in projects if isinstance(k, str) and _norm(k) == target), None)
    if key is None:
        # 새 항목: Claude 가 쓰는 정규화(윈도우=실제 케이스 forward-slash)에 최대한 맞춰 생성.
        key = str(Path(cwd).resolve()).replace("\\", "/") if os.name == "nt" else cwd

    entry = projects.get(key)
    if not isinstance(entry, dict):
        entry = {}
        projects[key] = entry
    if entry.get("hasTrustDialogAccepted") is True:
        return True   # 이미 신뢰 → 변경 없음

    entry["hasTrustDialogAccepted"] = True
    return _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


# ── Codex (~/.codex/config.toml) ──────────────────────────────────
_CODEX_SECTION_RE = re.compile(r"""(?m)^\[projects\.(?:'([^']*)'|"([^"]*)")\]\s*$""")


def pretrust_codex(cwd: str, path: Path | None = None) -> bool:
    """~/.codex/config.toml 에 [projects.'<cwd>'] trust_level="trusted" 섹션 보장.

    TOML 라이브러리 없이 텍스트로 안전 편집: 같은 폴더 섹션이 이미 있으면 건드리지 않고(중복
    섹션=TOML 오류 방지), 없을 때만 파일 끝에 새 섹션을 추가한다(단일 인용부호 리터럴 키라
    백슬래시·콜론 이스케이프 불필요).
    """
    path = path or (Path.home() / ".codex" / "config.toml")
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:  # noqa: BLE001
        return False

    target = _norm(cwd)
    for m in _CODEX_SECTION_RE.finditer(text):
        existing = m.group(1) if m.group(1) is not None else m.group(2)
        if _norm(existing) == target:
            return True   # 이미 이 폴더 섹션 있음 → 그대로(대개 trust_level 설정돼 있음)

    block = f"\n[projects.'{cwd}']\ntrust_level = \"trusted\"\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
        return True
    except Exception:  # noqa: BLE001
        return False


def _atomic_write(path: Path, content: str) -> bool:
    """임시파일 기록 후 원자적 교체(부분 기록으로 설정을 깨지 않게)."""
    try:
        tmp = path.with_name(path.name + ".vestige-tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001
        return False
