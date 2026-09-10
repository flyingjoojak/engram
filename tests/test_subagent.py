"""배경(서브에이전트) 대화 어댑터: 게이트(일회성 봇 제외)·세션 분리·래퍼 제거."""
import json
from pathlib import Path

from vestige.sources.subagent import SubagentAdapter, _strip_wrapper

PARENT = "4a545a78-parent-session"
AID = "a461background00"

_WRAP = ("The user sent a new message while you were working:\n{msg}\n\n"
         "This is how Claude Code surfaces messages the user sends mid-turn — "
         "within the running turn. Address the message above as you continue this turn.")


def _user(text, *, meta=False, wrap=False):
    content = _WRAP.format(msg=text) if wrap else text
    o = {"type": "user", "sessionId": PARENT, "uuid": f"u-{text[:6]}",
         "parentUuid": None, "timestamp": "2026-08-21T00:00:00Z",
         "cwd": "/c/proj", "isSidechain": True, "agentId": AID,
         "message": {"role": "user", "content": [{"type": "text", "text": content}]}}
    if meta:
        o["isMeta"] = True
    return o


def _assistant(text):
    return {"type": "assistant", "sessionId": PARENT, "isSidechain": True, "agentId": AID,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _write(path: Path, objs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(o) for o in objs) + "\n", encoding="utf-8")


def _interactive_agent():
    """Task 프롬프트 1 + 사람 후속 지시(isMeta) 2 → 게이트 통과 대상."""
    return [
        _user("Research CLI log formats"),           # 최초 Task 프롬프트(플래그 없음)
        _assistant("조사 시작합니다"),
        _user("48 머지하고 진행하자", meta=True, wrap=True),
        _assistant("머지했습니다"),
        _user("재빌드해줘", meta=True, wrap=True),
        _assistant("재빌드 완료"),
    ]


def _oneshot_helper():
    """Task 프롬프트 1개 + 응답뿐(사람 후속 지시 0) → 일회성 봇, 제외 대상."""
    return [
        _user("Review this code for bugs"),
        _assistant("리뷰 결과: 문제 없음"),
    ]


def test_strip_wrapper_removes_harness_text():
    wrapped = _WRAP.format(msg="머지해줘")
    assert _strip_wrapper(wrapped) == "머지해줘"
    assert _strip_wrapper("플래그 없는 원문") == "플래그 없는 원문"


def test_discover_gates_out_oneshot_helpers(tmp_path):
    root = tmp_path / "projects"
    _write(root / PARENT / "subagents" / f"agent-{AID}.jsonl", _interactive_agent())
    _write(root / PARENT / "subagents" / "agent-helper00000000.jsonl", _oneshot_helper())
    # 부모 세션 본체(서브에이전트 아님)도 하나 — discover 대상 아님.
    _write(root / PARENT / f"{PARENT}.jsonl", [_user("메인 질문")])

    found = {p.name for p in SubagentAdapter().discover(root)}
    assert found == {f"agent-{AID}.jsonl"}   # 상호작용 에이전트만, 일회성 봇 제외


def test_extract_turns_separates_session_and_strips_wrapper():
    a = SubagentAdapter()
    turns = a.extract_turns(_interactive_agent())
    # Task 프롬프트 1 + 후속 2 = 3턴
    assert len(turns) == 3
    # 세션이 부모가 아니라 agentId 로 분리됨
    assert all(t.session_id == AID for t in turns)
    assert all(t.id.startswith(AID + ":") for t in turns)
    # 래퍼가 벗겨져 사용자 원문만 질문에 남음
    assert turns[1].question == "48 머지하고 진행하자"
    assert turns[2].question == "재빌드해줘"


def test_source_name_is_claude_code():
    # 배경 에이전트도 결국 claude-code 도구 콘텐츠 → 저장 출처는 claude-code.
    assert SubagentAdapter.source_name == "claude-code"
    assert SubagentAdapter.name == "subagent"
