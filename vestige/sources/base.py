"""소스 어댑터 인터페이스: '어느 도구의 로그를, 어디서 찾아, 어떻게 읽어 공통 Turn으로 만드나'만 담당.

파이프라인(청킹·임베딩·저장·검색·정제)은 이 인터페이스 뒤의 도구가 뭔지 몰라도 된다.
라인 기반(JSONL 등) 소스 계약 4개만 구현하면 새 도구가 붙는다 — 기존 도구 로직은 건드리지 않는다.

새 도구(예: Aider·Cursor) 지원 추가법 → CONTRIBUTING.md 의 "새 소스 어댑터 추가하기" 참고.
어댑터는 in-process 로 돈다: 자기 루트의 로그를 읽어 Turn 을 반환하는 것 외에 네트워크 호출·임의 파일
쓰기·exec/eval 을 해서는 안 된다(보안 계약). 어댑터 자동 로더/플러그인 탐색은 도입하지 않는다 —
등록은 언제나 sources/__init__.py 의 명시적 import 를 거친다(신뢰 = 코드리뷰 게이트).

- name          : 레지스트리·설정·drift 키(내부 식별자, 예 "codex")
- source_name   : (선택) DB에 저장·검색 필터에 노출되는 출처명. 없으면 name 을 쓴다.
                  같은 도구의 하위 스트림을 합칠 때만 name 과 다르게 둔다(예: subagent → "claude-code").
- discover(root)            : 세션 파일(단위)들을 순회
- read_records(path, start) : (obj, end_offset) '완결' 레코드 산출(증분 tail-safe)
- is_turn_start(obj)        : 사람 질문 턴의 시작인지
- extract_turns(objs)       : 레코드 묶음 → 정규화 Turn 리스트
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, Protocol, runtime_checkable

from ..models import Turn


@runtime_checkable
class SourceAdapter(Protocol):
    name: str
    # DB에 저장되는 출처명. 대부분 name 과 같으므로 구현에서 생략 가능 —
    # 인덱서는 getattr(adapter, "source_name", adapter.name) 로 읽는다.
    source_name: str

    def discover(self, root: Path) -> Iterator[Path]: ...

    def read_records(self, path: str | Path, start_offset: int = 0) -> Iterator[tuple[dict, int]]: ...

    def is_turn_start(self, obj: dict) -> bool: ...

    def extract_turns(self, objs: Iterable[dict]) -> list[Turn]: ...
