"""PyInstaller 사이드카 진입점: FastAPI 백엔드를 로컬 포트에 띄운다.

Electron 메인이 이 exe를 spawn하고 포트를 넘긴다:
    vestige-backend.exe 8765      (또는 VESTIGE_PORT 환경변수)
"""

import multiprocessing
import os
import sys

# 배포(PyInstaller 프리즈) exe는 벡터 백엔드를 sqlite-vec(디스크·int8·저RAM)로 기본 설정.
# 개발(python) 실행은 npy 기본 유지. vestige import 전에 설정해야 config가 반영.
if getattr(sys, "frozen", False):
    os.environ.setdefault("VESTIGE_VECTOR_BACKEND", "sqlite-vec")
    # windowed(--noconsole) exe는 stdout/stderr가 None → 병렬 임베딩 멀티프로세싱 워커가 출력 시
    # 크래시(→ '빠른 재색인'이 매번 조용히 순차로 전락). import 시점에 devnull로 돌려 자식도 안전하게.
    # (웹 프로세스는 main()에서 app.log로 다시 지정. --mcp는 stdout이 파이프라 None이 아님 → 건드리지 않음)
    if sys.stdout is None or sys.stderr is None:
        _dn = open(os.devnull, "w")  # noqa: SIM115
        if sys.stdout is None:
            sys.stdout = _dn
        if sys.stderr is None:
            sys.stderr = _dn


# 프리즈 exe가 CLI로 불릴 때 웹서버 대신 넘겨줄 서브커맨드(vestige.cli 와 동일 집합).
_CLI_COMMANDS = frozenset({
    "search", "index", "enrich", "progress", "config", "setup", "app",
    "scheduler", "reconcile", "stats", "web", "sync", "syncthing",
})


def main() -> None:
    argv = list(sys.argv[1:])

    # 스케줄러/CLI가 프리즈 exe를 통해 부를 때의 형태: `vestige-backend.exe -m vestige index`.
    # PyInstaller exe는 파이썬 `-m 모듈` 실행을 못 해 이 인자를 무시하고 웹서버로 떨어졌다
    # (→ 색인 대신 웹이 혼자 열림). 접두를 걷어내고 CLI 로 디스패치한다.
    if argv[:2] == ["-m", "vestige"]:
        argv = argv[2:]

    # `vestige-backend.exe --mcp` → 웹 대신 MCP(stdio) 서버로 동작.
    # 이래야 exe만 받은 사용자도 별도 설치 없이 MCP를 등록·실행할 수 있다
    # (frozen exe는 `-m vestige.mcp_server`가 안 되므로 이 인자 모드가 유일한 경로).
    if "--mcp" in argv:
        from vestige.mcp_server import main as mcp_main
        mcp_main()
        return

    # 알려진 CLI 서브커맨드로 불렸으면(스케줄러 색인/정제/동기화 등) 웹서버가 아니라 CLI 실행.
    # 포트 숫자·무인자(더블클릭)는 아래 웹서버 경로 그대로.
    if argv and argv[0] in _CLI_COMMANDS:
        from vestige.cli import main as cli_main
        raise SystemExit(cli_main(argv))

    port = 8765
    if argv and argv[0].isdigit():
        port = int(argv[0])
    elif argv:
        # 숫자도, --mcp 도, 알려진 서브커맨드도 아닌 인자로 여기 왔다 = 웹서버로 폴백.
        # _CLI_COMMANDS 가 vestige.cli 서브파서와 drift 나면(새 커맨드 추가 후 목록 누락) 정확히
        # 이 경로로 조용히 새서, 예전 '웹이 혼자 열림' 버그가 재발한다. 최소한 흔적을 남긴다.
        print(f"[vestige-backend] 알 수 없는 인자 {argv!r} — 웹서버로 폴백(CLI 커맨드였다면 "
              f"_CLI_COMMANDS 목록 확인 필요)", file=sys.stderr)
    port = int(os.environ.get("VESTIGE_PORT", port))

    # managed=1: Electron 셸이 구동·감독. 셸이 창·단일인스턴스·로깅을 담당하므로 백엔드는
    # 순수 서버로만 동작(뮤텍스·브라우저 자동열기·app.log 리다이렉트 끔 → stdout은 셸이 캡처).
    managed = os.environ.get("VESTIGE_MANAGED") == "1"
    if getattr(sys, "frozen", False) and not managed:
        _setup_file_logging()                # windowed(콘솔 없음) 단독 실행에서 print/로그 보존
        # 단일 인스턴스: 프로세스 시작 즉시 네임드 뮤텍스로 판정. uvicorn은 모델 로딩(~15초) *후*에
        # 소켓을 잡으므로 포트 점유 검사로는 그 창에서 중복을 못 막아 10048 크래시가 났음(실측).
        if not _acquire_single_instance(port):
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{port}")
            return
        _open_browser_when_ready(port)       # 더블클릭 → 준비되면 브라우저 자동 오픈

    import uvicorn

    from vestige.web import app

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


_MUTEX: list = []   # 핸들 GC 방지(프로세스 생존 동안 뮤텍스 유지)


def _acquire_single_instance(port: int) -> bool:
    """Windows 네임드 뮤텍스로 같은 포트의 중복 웹 인스턴스를 막는다. 처음이면 True.
    프로세스 시작 즉시 판정하므로 모델 로딩 지연과 무관. 종료 시 OS가 자동 해제."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        h = ctypes.windll.kernel32.CreateMutexW(None, False, f"vestige-backend-singleton-{port}")
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            return False
        _MUTEX.append(h)   # 핸들 유지(프로세스 종료까지 뮤텍스 살아있게)
        return True
    except Exception:
        return True   # 뮤텍스 실패 시엔 그냥 진행


def _setup_file_logging() -> None:
    """windowed exe는 stdout/stderr가 없어 print가 깨질 수 있음 → data/app.log로 리다이렉트."""
    try:
        from vestige import config as C
        C.DATA_DIR.mkdir(parents=True, exist_ok=True)
        f = open(C.DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = f
        sys.stderr = f
    except Exception:  # noqa: BLE001 — 로그 리다이렉트 실패해도 앱은 떠야 함
        pass


def _open_browser_when_ready(port: int, timeout: float = 180.0) -> None:
    """포트가 열리면(=서버 준비) 기본 브라우저로 앱을 연다. 백그라운드 스레드."""
    import contextlib
    import socket
    import threading
    import time
    import webbrowser

    def wait_open():
        end = time.monotonic() + timeout   # 시스템 시계 변경(NTP 등)에 영향 안 받게
        while time.monotonic() < end:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            return
        with contextlib.suppress(Exception):
            webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=wait_open, daemon=True).start()


if __name__ == "__main__":
    # 병렬 임베딩(fastembed 멀티프로세싱)이 frozen exe에서 앱 전체를 재실행하지 않도록 필수.
    # 워커 spawn 시 이 가드가 인자를 가로채 처리 후 종료한다(없으면 exe 무한 재기동).
    multiprocessing.freeze_support()
    main()
