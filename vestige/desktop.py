"""데스크탑 앱: 웹 UI를 브라우저 탭이 아니라 네이티브 창에 띄운다(옵시디언 느낌).

기존 FastAPI 웹 UI를 그대로 재사용한다:
- uvicorn 서버를 백그라운드 스레드로 로컬 포트에 올리고,
- pywebview 로 그 주소를 가리키는 OS 네이티브 창을 연다(Windows=Edge WebView2).

임베딩 모델은 서버 시작 시 로드(~15초)되며, 그동안 창은 즉시 열리고
검색은 "모델 로딩 중"으로 대기하다 준비되면 동작한다.

실행:  vestige app   (또는 python -m vestige.desktop)
"""

from __future__ import annotations

import socket
import threading
import time

DEFAULT_PORT = 8642
WIN_TITLE = "Vestige"


def _free_port(preferred: int = DEFAULT_PORT) -> int:
    """선호 포트가 비었으면 그대로, 아니면 OS가 준 임의 빈 포트."""
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", candidate))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def _serve(port: int):
    """uvicorn 서버를 이 스레드에서 실행. (비-메인 스레드라 시그널 핸들러는 자동 skip)"""
    import uvicorn

    from . import web

    config = uvicorn.Config(web.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def _wait_until_up(port: int, timeout: float = 20.0) -> bool:
    """서버가 연결을 받을 때까지 대기(창을 빈 화면으로 열지 않도록)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def run(port: int | None = None) -> None:
    import webview  # 지연 임포트: 데스크탑 extra 없이도 나머지 CLI는 동작

    port = _free_port(port or DEFAULT_PORT)
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _wait_until_up(port)  # HTTP 소켓 오픈 대기(모델 로딩은 페이지가 알아서 처리)

    webview.create_window(WIN_TITLE, f"http://127.0.0.1:{port}",
                          width=1100, height=800, min_size=(720, 520))
    webview.start()  # 창을 닫으면 반환 → 데몬 서버 스레드도 함께 종료


if __name__ == "__main__":
    run()
