"""소스 어댑터 레지스트리.

현재 등록: Claude Code · Codex · Subagent. 새 도구(Aider·Cursor 등)를 지원하려면 아래 ADAPTERS 에
어댑터 인스턴스를 추가하면 되고, 파이프라인(indexer/chunker/embedder/store/search)은 건드릴 필요가 없다.
추가 방법 단계별 가이드 → 프로젝트 루트 CONTRIBUTING.md "새 소스 어댑터 추가하기".

보안: 등록은 반드시 이 파일의 '명시적 import'를 거친다(자동 플러그인 로더 없음). 3자 어댑터가
사용자 머신에 도달하는 유일한 경로는 PR → 코드리뷰 → 릴리스이며, 이게 신뢰 게이트다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base import SourceAdapter
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter
from .subagent import SubagentAdapter

logger = logging.getLogger(__name__)

# 등록된 어댑터들(이름 → 인스턴스). 새 도구를 지원하려면 여기에 인스턴스를 추가.
ADAPTERS: dict[str, SourceAdapter] = {
    ClaudeCodeAdapter.name: ClaudeCodeAdapter(),
    CodexAdapter.name: CodexAdapter(),
    SubagentAdapter.name: SubagentAdapter(),
}


def default_adapter() -> SourceAdapter:
    """현재 기본 소스(Claude Code). projects_dir 를 명시적으로 넘긴 하위호환 경로에서 쓴다."""
    return ADAPTERS["claude-code"]


def source_roots() -> dict[str, Path]:
    """소스명 → 로그 루트(설정을 런타임에 읽어 재시작 없이 반영)."""
    from .. import config as C
    return {
        "claude-code": Path(C.PROJECTS_DIR),
        "codex": Path(C.CODEX_SESSIONS_DIR),
        # 서브에이전트 대화는 Claude Code 프로젝트 폴더 안(<부모>/subagents/)에 있다.
        "subagent": Path(C.PROJECTS_DIR),
    }


def disabled_sources() -> set[str]:
    """UI 토글로 끈 소스(DB meta 'sources_disabled'). DB 접근 실패 시 빈 집합(전부 활성).

    끄기 = 색인만 중단(비파괴). 기존 색인 데이터는 그대로 남아 검색된다.
    """
    try:
        from ..store import ArchiveDB
        raw = ArchiveDB().get_meta("sources_disabled") or ""
    except Exception:  # noqa: BLE001 — DB 미준비/락이어도 색인 결정이 죽지 않게
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def parent_source(name: str) -> str:
    """어댑터가 저장·노출하는 출처명(source_name). 대부분 name 과 같다.

    subagent 처럼 name≠source_name 인 '하위 스트림'은 부모 출처(여기선 claude-code)로 접힌다:
    검색에서도 부모 출처로 나오고, 켜기/끄기도 부모 토글 하나만 따른다(자기 토글 없음).
    """
    a = ADAPTERS.get(name)
    return getattr(a, "source_name", name) if a is not None else name


def is_substream(name: str) -> bool:
    """하위 스트림(자기 토글 없이 부모 출처를 따르는 어댑터)인가."""
    return parent_source(name) != name


def toggleable_source_names() -> list[str]:
    """사용자 설정에 on/off 토글로 노출할 소스명(= 부모 출처인 것만, 하위 스트림 제외)."""
    return [n for n in ADAPTERS if not is_substream(n)]


def enabled_source_names() -> list[str]:
    """색인 대상 소스명. VESTIGE_SOURCES(쉼표)로 한정하거나 비면 전부에서, UI로 끈 소스를 제외.

    하위 스트림(subagent)은 자기 이름이 아니라 부모 출처(claude-code)의 disabled 여부만 따른다.
    중복 제거·순서 유지, env의 미등록 이름은 경고.
    """
    from .. import config as C
    if C.SOURCES_ENV:
        wanted = [s.strip() for s in C.SOURCES_ENV.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in ADAPTERS]
        if unknown:
            logger.warning("VESTIGE_SOURCES에 알 수 없는 소스 %s 무시(사용 가능: %s)",
                           unknown, list(ADAPTERS.keys()))
        base = list(dict.fromkeys(s for s in wanted if s in ADAPTERS))
    else:
        base = list(ADAPTERS.keys())
    disabled = disabled_sources()
    # 하위 스트림은 부모의 disabled 만 확인(자기 이름의 레거시 disabled 항목은 무시 → 부모를 따른다).
    return [n for n in base if parent_source(n) not in disabled]   # 중복 제거+순서 유지


def active_sources() -> list[tuple[str, SourceAdapter, Path]]:
    """색인 대상 (이름, 어댑터, 루트) 목록. 루트가 실제로 존재하는 소스만(없으면 조용히 제외)."""
    roots = source_roots()
    out: list[tuple[str, SourceAdapter, Path]] = []
    for name in enabled_source_names():
        adapter = ADAPTERS.get(name)
        root = roots.get(name)
        if adapter is not None and root is not None and root.exists():
            out.append((name, adapter, root))
    return out


__all__ = [
    "SourceAdapter", "ClaudeCodeAdapter", "CodexAdapter", "SubagentAdapter",
    "ADAPTERS", "default_adapter", "active_sources", "enabled_source_names",
    "source_roots", "disabled_sources", "parent_source", "is_substream",
    "toggleable_source_names",
]
