"""데스크탑 앱 순수 로직 테스트 (GUI·서버 없이 포트 선택만)."""

from __future__ import annotations

import socket

from vestige import desktop


def test_free_port_prefers_given_when_available():
    # OS가 준 확실히 빈 포트를 선호값으로 넣으면 그대로 반환.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    got = desktop._free_port(free)
    assert got == free


def test_free_port_falls_back_when_busy():
    # 선호 포트를 점유한 채 요청하면 다른(0이 아닌) 포트를 준다.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        got = desktop._free_port(taken)
        assert got != taken and got > 0
