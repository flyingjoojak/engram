"""schema_report: 리다acted 지문·드리프트 감지·대화 유출 0 테스트."""
import json
from pathlib import Path

from vestige import config, schema_report

SID = "019e80dc-1754-7422-b72f-2d176635efb2"
SECRET = "TOP_SECRET_CONVERSATION_XYZ"


def _codex_root(tmp_path: Path, lines: list[str]) -> Path:
    root = tmp_path / "sessions"
    d = root / "2026" / "08" / "21"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"rollout-2026-08-21T10-00-00-{SID}.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return root


# ── redact ────────────────────────────────────────────────────
def test_redact_strips_conversation_text():
    obj = {
        "type": "event_msg",
        "payload": {"type": "user_message", "message": SECRET, "images": []},
    }
    red = schema_report.redact(obj)
    dumped = json.dumps(red, ensure_ascii=False)
    assert SECRET not in dumped                 # 대화 유출 0
    assert red["type"] == "event_msg"           # 판별자 유지
    assert red["payload"]["type"] == "user_message"
    assert red["payload"]["message"].startswith("<str:")  # 내용 → 길이 표식


def test_redact_does_not_leak_content_via_whitelisted_keys():
    # 화이트리스트 키(name/source)라도 값이 '토큰'이 아니면(경로·프로즈) 리댁션돼야 함.
    obj = {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "name": "apply_patch",   # 짧은 토큰 → 유지 OK
            "parsed_cmd": [{"type": "read", "name": f"/Users/me/secret/{SECRET}.md", "cmd": SECRET}],
            "source": f"file:///C:/Users/me/{SECRET}",
        },
    }
    dumped = json.dumps(schema_report.redact(obj), ensure_ascii=False)
    assert SECRET not in dumped                        # 경로·명령 유출 0
    red = schema_report.redact(obj)
    assert red["payload"]["name"] == "apply_patch"     # 짧은 판별자 토큰은 유지
    assert red["payload"]["parsed_cmd"][0]["type"] == "read"
    assert red["payload"]["parsed_cmd"][0]["name"].startswith("<str:")   # 경로는 리댁션
    assert red["payload"]["source"].startswith("<str:")                  # file:// 경로 리댁션


def test_redact_keeps_numbers_and_discriminators():
    red = schema_report.redact({"role": "assistant", "exit_code": 0, "text": "hello"})
    assert red["role"] == "assistant"
    assert red["exit_code"] == 0
    assert red["text"] == "<str:5>"


def test_redact_caps_long_arrays():
    red = schema_report.redact({"xs": list(range(100))})
    # 앞 일부 + '<+N more>' 표식
    assert len(red["xs"]) <= schema_report._MAX_ARRAY + 1
    assert any(isinstance(x, str) and "more" in x for x in red["xs"])


# ── build_report ──────────────────────────────────────────────
def test_build_report_unknown_source():
    r = schema_report.build_report("nope")
    assert "error" in r


def test_build_report_missing_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", tmp_path / "nonexistent")
    r = schema_report.build_report("codex")
    assert r["root_exists"] is False
    assert r["files"] == 0


def test_build_report_ok_no_drift(tmp_path, monkeypatch):
    root = _codex_root(tmp_path, [
        f'{{"timestamp":"t","type":"session_meta","payload":{{"id":"{SID}","cwd":"/p","cli_version":"0.149.0"}}}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"user_message","message":"' + SECRET + '"}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"agent_message","message":"reply"}}',
    ])
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", root)
    r = schema_report.build_report("codex")
    assert r["root_exists"] is True
    assert r["files_scanned"] == 1
    assert r["drift_suspected"] is False
    assert "0.149.0" in r["cli_versions"]
    assert r["payload_type_counts"].get("user_message") == 1
    # 정상 파일도 샘플은 첨부되지만 대화는 유출되지 않아야 함
    assert SECRET not in json.dumps(r, ensure_ascii=False)


def test_build_report_mixed_files_not_flagged(tmp_path, monkeypatch):
    # 정상 대화 파일 1개 + 서브에이전트/명령 전용처럼 0턴 파일 1개 → 오탐 없이 드리프트 False.
    root = tmp_path / "sessions"
    d = root / "2026" / "08" / "21"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"rollout-2026-08-21T10-00-00-{SID}.jsonl").write_text("\n".join([
        f'{{"timestamp":"t","type":"session_meta","payload":{{"id":"{SID}","cwd":"/p","cli_version":"0.149.0"}}}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"user_message","message":"hi"}}',
        '{"timestamp":"t","type":"event_msg","payload":{"type":"agent_message","message":"yo"}}',
    ]) + "\n", encoding="utf-8")
    zero = ['{"timestamp":"t","type":"session_meta","payload":{"id":"z","cwd":"/p"}}']
    for _ in range(8):
        zero.append('{"timestamp":"t","type":"turn_context","payload":{"type":"x"}}')
    (d / "rollout-2026-08-21T11-00-00-019e80dd-1754-7422-b72f-2d176635efb2.jsonl").write_text(
        "\n".join(zero) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", root)
    r = schema_report.build_report("codex")
    assert r["files_scanned"] == 2
    assert r["files_with_turns"] == 1
    assert r["drift_suspected"] is False   # 일부만 0턴이면 드리프트 아님(오탐 억제)
    assert r["suspect_files"] == 0


def test_build_report_claude_all_sdk_not_drift(tmp_path, monkeypatch):
    """claude-code(#125): 전부 sdk 자동화라 0턴이어도, 구조는 읽히므로 드리프트 오탐 억제."""
    monkeypatch.setenv("VESTIGE_SKIP_SDK_SESSIONS", "1")   # sdk 제외 강제 ON(결정적)
    root = tmp_path / "projects"
    d = root / "proj"
    d.mkdir(parents=True)
    lines = []
    for i in range(6):
        lines.append(json.dumps({"type": "user", "uuid": f"u{i}", "parentUuid": None, "sessionId": "s",
                                 "cwd": "/p", "timestamp": "t", "promptSource": "sdk", "isSidechain": False,
                                 "message": {"role": "user", "content": f"자동화 작업 {i}"}}))
        lines.append(json.dumps({"type": "assistant", "sessionId": "s",
                                 "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}))
    (d / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECTS_DIR", root)
    r = schema_report.build_report("claude-code")
    assert r["files_with_turns"] == 0            # sdk 제외로 턴 0
    assert r["readable_user_prompts"] >= 6        # 그러나 구조는 읽힘
    assert r["drift_suspected"] is False          # → 오탐 억제


def test_build_report_claude_unreadable_is_drift(tmp_path, monkeypatch):
    """claude-code(#125): user 메시지 구조 자체를 못 읽으면(진짜 포맷 변경) 드리프트 True."""
    root = tmp_path / "projects"
    d = root / "proj"
    d.mkdir(parents=True)
    lines = [json.dumps({"type": "brand-new-record", "blob": f"x{i}"}) for i in range(8)]
    (d / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECTS_DIR", root)
    r = schema_report.build_report("claude-code")
    assert r["files_with_turns"] == 0
    assert r["readable_user_prompts"] == 0
    assert r["drift_suspected"] is True


def test_build_report_detects_drift_and_no_leak(tmp_path, monkeypatch):
    # 미래 포맷 흉내: event_msg 는 많은데 어댑터가 아는 사용자 턴이 없음 → 턴 0 → 드리프트.
    lines = [f'{{"timestamp":"t","type":"session_meta","payload":{{"id":"{SID}","cwd":"/p","cli_version":"0.200.0"}}}}']
    for i in range(8):
        lines.append(
            '{"timestamp":"t","type":"event_msg","payload":{"type":"brand_new_event",'
            '"blob":"' + SECRET + str(i) + '"}}'
        )
    root = _codex_root(tmp_path, lines)
    monkeypatch.setattr(config, "CODEX_SESSIONS_DIR", root)
    r = schema_report.build_report("codex")
    assert r["drift_suspected"] is True
    assert r["suspect_files"] == 1
    assert "brand_new_event" in r["payload_type_counts"]
    assert r["redacted_samples"]                       # 샘플 첨부됨
    assert SECRET not in json.dumps(r, ensure_ascii=False)   # 그래도 유출 0
    assert "0.200.0" in r["cli_versions"]
