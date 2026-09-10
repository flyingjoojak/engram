"""'원클릭 형식 신고'용 리다acted 스키마 지문 생성.

목적: 어떤 소스(codex 등)의 로그 스키마가 바뀌어 어댑터가 대화를 놓칠 때, 사용자가
**대화 내용을 담지 않고** 구조 정보만 개발자에게 신고할 수 있게 한다(프라이버시 우선).

리다acted 원칙:
- 키 이름은 유지(스키마 이해에 필요).
- 판별자로 쓰이는 안전 키(type/role/status/name/kind/phase/cli_version/originator/source/
  model_provider)의 문자열 값만 유지 — 이건 대화가 아니라 스키마 태그다.
- 그 외 모든 문자열은 ``<str:LEN>`` 로 치환(내용 유출 0). 숫자/불리언/null 은 유지.
- 배열은 앞쪽 일부만 샘플링(크기 억제).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import config

if TYPE_CHECKING:
    from .sources.base import SourceAdapter

REPO = "flyingjoojak/vestige"

# 문자열 값을 그대로 남겨도 되는(=대화가 아닌 판별자) 키.
# ⚠️ 키 이름만으로는 부족하다: name/source/status 는 다른 위치에서 실제 내용(경로·프로즈)을
# 담을 수 있으므로, 값이 '짧은 토큰'일 때만 유지한다(공백·슬래시·개행 있으면 리댁션).
_SAFE_VALUE_KEYS = frozenset({
    "type", "role", "status", "name", "kind", "phase",
    "cli_version", "originator", "source", "model_provider",
})
_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")
_MAX_KEY_LEN = 80

_MAX_FILES = 100          # 스캔 파일 상한(진단 샘플이므로 전수 아님)
_MAX_RECORDS_PER_FILE = 1000
_MAX_ARRAY = 4            # 배열 샘플 길이 상한
_MAX_DEPTH = 8
_MAX_SAMPLES = 12         # 리다acted 예시 레코드 상한(고유 조합별 1개)


def _vestige_version() -> str:
    try:
        from importlib.metadata import version
        return version("vestige")
    except Exception:  # noqa: BLE001
        return "unknown"


def source_root(source: str) -> Path | None:
    """소스별 로그 루트. 어댑터 레지스트리와 동일 해석(설정 CODEX_SESSIONS_DIR 등 반영). 미지원=None."""
    from .sources import source_roots
    return source_roots().get(source)


def redact(value: Any, depth: int = 0) -> Any:
    """대화 내용을 제거하고 구조만 남긴다(문자열 → <str:LEN>, 안전 키 값은 유지)."""
    if depth > _MAX_DEPTH:
        return "<...>"
    if isinstance(value, str):
        return f"<str:{len(value)}>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = k if isinstance(k, str) and len(k) <= _MAX_KEY_LEN else str(k)[:_MAX_KEY_LEN]
            # 안전 키라도 '짧은 판별자 토큰'일 때만 값 유지 — 경로·프로즈(공백/슬래시/개행)는 리댁션.
            if k in _SAFE_VALUE_KEYS and isinstance(v, str) and _SAFE_VALUE_RE.match(v):
                out[key] = v
            else:
                out[key] = redact(v, depth + 1)
        return out
    if isinstance(value, list):
        sample = [redact(v, depth + 1) for v in value[:_MAX_ARRAY]]
        if len(value) > _MAX_ARRAY:
            sample.append(f"<+{len(value) - _MAX_ARRAY} more>")
        return sample
    return f"<{type(value).__name__}>"


def _iter_raw(path: Path, cap: int):
    """파일을 스트리밍으로 읽어 최대 cap개 JSON 레코드만 산출(전체 파일 메모리 적재 방지)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= cap:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _combo(obj: dict) -> str:
    """레코드의 스키마 조합 키(type/payload.type/item.type)."""
    t = obj.get("type")
    pl = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    pt = pl.get("type")
    item = pl.get("item") if isinstance(pl, dict) else None
    it = item.get("type") if isinstance(item, dict) else None
    return "/".join(str(x) for x in (t, pt, it) if x)


def _count_turns(adapter: "SourceAdapter", recs: list[dict]) -> int:
    starts = [i for i, o in enumerate(recs) if adapter.is_turn_start(o)]
    total = 0
    for k, si in enumerate(starts):
        sj = starts[k + 1] if k + 1 < len(starts) else len(recs)
        total += len(adapter.extract_turns(recs[si:sj]))
    return total


def build_report(source: str) -> dict:
    """소스의 리다acted 스키마 지문 + 드리프트 의심 여부."""
    from .sources import ADAPTERS

    base: dict[str, Any] = {
        "source": source,
        "vestige_version": _vestige_version(),
        "repo": REPO,
    }
    adapter = ADAPTERS.get(source)
    if adapter is None:
        return {**base, "error": f"알 수 없는 소스: {source}"}

    root = source_root(source)
    if not root or not root.exists():
        return {**base, "root": str(root) if root else None, "root_exists": False, "files": 0}

    type_counts: Counter[str] = Counter()
    ptype_counts: Counter[str] = Counter()
    itype_counts: Counter[str] = Counter()
    cli_versions: set[str] = set()
    n_files = 0
    files_with_turns = 0
    zero_turn_files = 0
    unreadable_files = 0
    total_records = 0
    # claude-code 한정: 구조적으로 읽히는(role=user + 텍스트) 사용자 프롬프트 수.
    # >0 이면 포맷 자체는 읽히는 것(0턴은 sdk/plumbing 필터로 제외됐을 뿐) → 드리프트 오탐 억제.
    readable_user_prompts = 0
    _user_text = None
    if source == "claude-code":
        from .parser import _user_text as _user_text  # noqa: PLC0415
    samples: dict[str, Any] = {}   # combo -> redacted record
    first_recs: list[dict] | None = None

    for f in adapter.discover(root):
        if n_files >= _MAX_FILES:
            break
        n_files += 1
        try:
            recs: list[dict] = list(_iter_raw(f, _MAX_RECORDS_PER_FILE))  # 스트리밍(전체 적재 X)
            total_records += len(recs)
            if first_recs is None:
                first_recs = recs
            for o in recs:
                if not isinstance(o, dict):
                    continue
                t = o.get("type")
                if t:
                    type_counts[str(t)] += 1
                if _user_text is not None and t == "user":
                    m = o.get("message")
                    if isinstance(m, dict) and m.get("role") == "user" and _user_text(m.get("content")) is not None:
                        readable_user_prompts += 1
                pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
                pt = pl.get("type")
                if pt:
                    ptype_counts[str(pt)] += 1
                item = pl.get("item") if isinstance(pl, dict) else None
                if isinstance(item, dict) and item.get("type"):
                    itype_counts[str(item["type"])] += 1
                if t == "session_meta" and pl.get("cli_version"):
                    cli_versions.add(str(pl["cli_version"]))
            if _count_turns(adapter, recs) > 0:
                files_with_turns += 1
            else:
                zero_turn_files += 1
                _collect_samples(recs, samples)   # 0턴 파일 = 신고에 가장 유용한 샘플
        except Exception:  # noqa: BLE001 — 파일 하나가 깨져도 전체 스캔이 죽지 않게(신고 기능이라 특히 중요)
            unreadable_files += 1
            continue

    # 드리프트 의심: 스캔한 어떤 파일에서도 턴을 못 뽑음(=어댑터가 포맷을 전혀 못 읽음).
    # 서브에이전트·명령 전용 파일은 정상적으로 0턴이라, '전부 0턴'일 때만 의심(오탐 억제).
    # 한계(알려진): 일부 파일만 새 포맷이면(업그레이드 직후 구/신 혼재) files_with_turns>0 이라
    #   여기선 안 잡힌다. 그 경우는 payload_type_counts/item_type_counts 로 개발자가 눈으로 확인.
    drift = n_files > 0 and files_with_turns == 0 and total_records > 5
    # claude-code: 읽히는 사용자 프롬프트가 하나라도 있으면 포맷은 정상(전부 sdk/plumbing 제외일 뿐) → 오탐 아님.
    if source == "claude-code" and readable_user_prompts > 0:
        drift = False

    # 샘플이 없으면(=전부 턴 있음) 첫 파일에서 정상 스키마 샘플 첨부.
    if not samples and first_recs:
        _collect_samples(first_recs, samples)

    return {
        **base,
        "root": str(root),
        "root_exists": True,
        "files_scanned": n_files,
        "files_with_turns": files_with_turns,
        "readable_user_prompts": readable_user_prompts,
        "unreadable_files": unreadable_files,
        "cli_versions": sorted(cli_versions),
        "drift_suspected": drift,
        "suspect_files": zero_turn_files if drift else 0,
        "type_counts": dict(type_counts.most_common()),
        "payload_type_counts": dict(ptype_counts.most_common()),
        "item_type_counts": dict(itype_counts.most_common()),
        "redacted_samples": list(samples.values()),
    }


def _collect_samples(recs: list[dict], samples: dict[str, Any]) -> None:
    for o in recs:
        if len(samples) >= _MAX_SAMPLES:
            return
        key = _combo(o) or "?"
        if key not in samples:
            samples[key] = redact(o)
