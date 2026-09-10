"""CLI: `mem "질의"` 검색, `mem index` 백필/증분, `mem stats` 현황.

로직은 전부 코어 모듈에 있고 여기선 얇게 호출만 한다(나중 자체앱이 같은 코어 재사용).
"""

from __future__ import annotations

import argparse
import sys

from .config import DB_PATH, EMBED_MODEL
from .search import search as run_search
from .store import ArchiveDB
from .vectorindex import make_index


def _open(need_embedder: bool):
    db = ArchiveDB()
    vi = make_index()
    embedder = None
    if need_embedder:
        stored = db.get_meta("embed_model")
        if stored and stored != EMBED_MODEL:
            print(f"[경고] 인덱스 모델({stored}) ≠ 설정 모델({EMBED_MODEL}). 재색인 필요.",
                  file=sys.stderr)
        from .embedder import Embedder  # 무거운 임포트 지연
        embedder = Embedder()
    return db, vi, embedder


def _trunc(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + "..."


def _kst(ts: str) -> str:
    """UTC 저장 타임스탬프 → KST(YYYY-MM-DD HH:MM) 표시. 파싱 실패 시 원문 앞부분."""
    from datetime import datetime, timedelta, timezone
    try:
        dt = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return (ts or "")[:16].replace("T", " ")


def cmd_search(args: argparse.Namespace) -> int:
    db, vi, embedder = _open(need_embedder=True)
    if len(vi) == 0:
        print("인덱스가 비어있습니다. 먼저 `mem index` 로 백필하세요.")
        return 1
    hits = run_search(args.query, db, vi, embedder, k=args.k,
                      session=args.session, since=args.since, until=args.until,
                      keyword=not args.semantic_only)
    if not hits:
        print("결과 없음.")
        return 0
    for i, h in enumerate(hits, 1):
        t = h.turn
        via = "+".join(h.sources) if h.sources else "?"
        cos = f"cos={h.cosine:.3f}" if h.cosine is not None else "키워드"
        print(f"\n[{i}] [{via}] {cos}  {_kst(t.timestamp)}  세션 {t.session_id[:8]}")
        print(f"    Q: {_trunc(t.question, 200)}")
        print(f"    A: {_trunc(t.answer, 200)}")
        if t.actions:
            print(f"    행동: {_trunc(t.action_summary(), 160)}")
        if h.summary:
            print(f"    - 정제: {_trunc(h.summary, 160)}")
        if h.tags:
            print(f"    - 태그: {', '.join(h.tags)}")
        print(f"    - 스레드 {len(h.thread)}턴")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from .config import EMBED_MODEL, MIN_FREE_MB
    from .indexer import has_new_data, index_all, reconcile
    from .keepawake import keep_system_awake
    from .logutil import batch_log
    from .sysmem import available_mb, set_low_priority

    set_low_priority()  # 포그라운드 작업에 CPU 양보

    db = ArchiveDB()   # 값싼 오픈(모델 로드 없음)
    vi = make_index()

    # 크로스-프로세스 상호배제: 웹(Electron 셸) 인-프로세스 색인/재색인과 동시에 같은
    # archive.db·벡터 인덱스를 건드리지 않게. reconcile(벡터 저장 포함)부터 락 아래에서 수행한다
    # — 다른 프로세스가 색인 중이면 이번 실행은 통째로 건너뛴다(다음 주기 재시도).
    from .proclock import IndexLock
    _xlock = IndexLock()
    if not _xlock.acquire():
        msg = "다른 프로세스가 색인 중 — 이번 실행 건너뜀(다음 주기 재시도)"
        print(msg)
        batch_log(msg)
        return 0
    try:
        # 0) 고아 벡터 정리(모델 불필요·값쌈) — 매 회차 안전망.
        try:
            reconcile(db, vi, log_fn=batch_log)
        except Exception as ex:
            batch_log(f"reconcile 오류: {ex}")

        # 1) 새 대화 없으면 모델 로드조차 안 하고 즉시 종료(자리 비우면 스파이크 0). 로그도 안 남김.
        if not args.force and not has_new_data(db):
            return 0

        # 2) 메모리 가드: RAM 빠듯하면 이번 회차 건너뜀(커서라 손실 0).
        avail = available_mb()
        if avail is not None and avail < MIN_FREE_MB and not args.force:
            msg = f"메모리 부족({avail}MB < {MIN_FREE_MB}MB) — 이번 배치 건너뜀(다음 주기 재시도). 강제: --force"
            print(msg)
            batch_log(msg)
            return 0

        # 3) 여기서만 무거운 임베딩 모델 로드
        stored = db.get_meta("embed_model")
        if stored and stored != EMBED_MODEL:
            print(f"[경고] 인덱스 모델({stored}) ≠ 설정 모델({EMBED_MODEL}). 재색인 필요.", file=sys.stderr)
        from .embedder import Embedder
        embedder = Embedder()

        def log(msg: str) -> None:
            print(msg)
            batch_log(msg)

        with keep_system_awake():  # 인덱싱 도중만 시스템 절전 방지(모니터는 꺼져도 됨)
            total = index_all(db, vi, embedder, recent_first=not args.oldest_first, log_fn=log)
        log(f"완료: 총 {total} 턴 인덱싱. 벡터 {len(vi)}개.")
    finally:
        _xlock.release()
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    from .config import ENRICH_BACKEND
    from .enrich import backend_available, enrich_all, enrich_session
    from .keepawake import keep_system_awake
    from .logutil import batch_log

    backend = args.backend or ENRICH_BACKEND
    ok, why = backend_available(backend)
    if not ok:
        print(f"정제 건너뜀 (backend={backend}): {why}")
        return 0

    db, _vi, _ = _open(need_embedder=False)

    def log(msg: str) -> None:
        print(msg)
        batch_log(msg)

    # 정제 도중 시스템 절전 방지(오래 걸리는 야간 작업이 중간에 안 멈추게).
    with keep_system_awake():
        if args.session:
            n = enrich_session(args.session, db, backend=backend, model=args.model)
            log(f"세션 {args.session[:8]}: {n}턴 정제 (backend={backend})")
        else:
            total = enrich_all(db, backend=backend, model=args.model,
                               only_missing=not args.all, limit=args.limit, log_fn=log)
            log(f"완료: 총 {total}턴 정제 (backend={backend}).")
    return 0


def cmd_progress(args: argparse.Namespace) -> int:
    from .sources import active_sources

    db, vi, _ = _open(need_embedder=False)
    # total = 커서와 같은 집합(활성 소스 전체가 발견하는 파일)으로 세야 done/total 이 맞는다.
    # 구버전은 Claude Code 폴더만 세서 Codex 파일이 들어가면 done>total(>100%)이 됐다.
    total = 0
    for _name, adapter, root in active_sources():
        try:
            total += sum(1 for _ in adapter.discover(root))
        except Exception:  # noqa: BLE001 — 한 소스 walk 실패가 진행률 출력을 막지 않게
            pass
    done = db.conn.execute("SELECT COUNT(*) c FROM cursors").fetchone()["c"]
    turns = db.conn.execute("SELECT COUNT(*) c FROM turns").fetchone()["c"]
    chunks = db.conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
    sess = db.conn.execute("SELECT COUNT(DISTINCT session_id) c FROM turns").fetchone()["c"]
    pct = min(100.0, 100 * done / total) if total else 0.0   # 파일 삭제 등으로 done>total 이어도 100% 상한
    filled = min(25, int(pct // 4))
    bar = "#" * filled + "-" * (25 - filled)
    print(f"[{bar}] {min(done, total)}/{total} 파일 ({pct:.1f}%)")
    print(f"누적: 세션 {sess} · 턴 {turns} · 청크/벡터 {chunks}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """현재 유효 설정 + 설정 파일 위치 표시(값이 어디서 왔는지 확인용)."""
    from . import config as C

    exists = C.CONFIG_PATH.exists()
    print(f"설정 파일: {C.CONFIG_PATH}  ({'있음' if exists else '없음 — 만들면 자동 로드'})")
    print(f"데이터 경로: {C.DATA_DIR}")
    print(f"로그 소스: {C.PROJECTS_DIR}")
    print("--- 정제 백엔드 ---")
    print(f"VESTIGE_ENRICH_BACKEND = {C.ENRICH_BACKEND}")
    print(f"  claude 모델   = {C.ENRICH_CLI_MODEL}")
    print(f"  anthropic 모델 = {C.ENRICH_API_MODEL}")
    print(f"  openai 모델   = {C.ENRICH_OPENAI_MODEL}")
    print(f"  gemini 모델   = {C.ENRICH_GEMINI_MODEL}")
    print(f"  ollama 모델   = {C.ENRICH_OLLAMA_MODEL}  @ {C.ENRICH_OLLAMA_URL}")
    # 키 존재 여부만(값은 절대 출력하지 않음).
    import os
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        print(f"  {key}: {'설정됨' if os.environ.get(key) else '없음'}")
    print("--- 임베딩 ---")
    print(f"VESTIGE_EMBED_MODEL = {C.EMBED_MODEL}")
    if not exists:
        print(f"\n힌트: `{C.CONFIG_PATH.name}` 를 만들어 KEY=VALUE 로 적으면 CLI·스케줄러·웹이 모두 읽습니다.")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    """원문 없는 고아 벡터 수동 정리."""
    from .indexer import reconcile
    db, vi, _ = _open(need_embedder=False)
    n = reconcile(db, vi, log_fn=print)
    if n == 0:
        print("정리할 고아 벡터 없음.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db, vi, _ = _open(need_embedder=False)
    turns = db.conn.execute("SELECT COUNT(*) c FROM turns").fetchone()["c"]
    chunks = db.conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
    sessions = db.conn.execute("SELECT COUNT(DISTINCT session_id) c FROM turns").fetchone()["c"]
    enriched = db.conn.execute("SELECT COUNT(*) c FROM turns WHERE summary IS NOT NULL").fetchone()["c"]
    print(f"DB: {DB_PATH}")
    print(f"세션 {sessions} · 턴 {turns} · 청크 {chunks} · 벡터 {len(vi)} · 정제완료 {enriched}")
    print(f"임베딩 모델: {db.get_meta('embed_model') or '(미설정)'}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """최초 온보딩: 데이터 폴더·설정 파일 생성 + OS별 스케줄러 등록 + 다음 단계 안내."""
    from . import config as C

    # 1) 데이터 폴더
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[1/4] 데이터 폴더: {C.DATA_DIR}")

    # 2) 설정 파일 — 없으면 내장 템플릿으로 생성(있으면 건드리지 않음).
    #    템플릿을 코드에 내장 → pip 설치(비-editable)에서도 항상 동작.
    if C.CONFIG_PATH.exists():
        print(f"[2/4] 설정 파일 이미 있음: {C.CONFIG_PATH} (유지)")
    else:
        C.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        C.CONFIG_PATH.write_text(C.CONFIG_TEMPLATE, encoding="utf-8")
        print(f"[2/4] 설정 파일 생성: {C.CONFIG_PATH} (필요한 줄만 주석 해제)")

    # 3) 로그 소스 존재 확인
    src_ok = C.PROJECTS_DIR.exists()
    print(f"[3/4] 로그 소스: {C.PROJECTS_DIR} ({'있음' if src_ok else '없음 — Claude Code 사용 이력 필요'})")

    # 4) 스케줄러 자동 등록(OS별). --no-scheduler 로 생략, --dry-run 로 미리보기.
    from . import scheduler
    if getattr(args, "no_scheduler", False):
        print(f"[4/4] 스케줄러: 건너뜀 (현재: {scheduler.status()})")
    else:
        try:
            lines = scheduler.install(dry_run=getattr(args, "dry_run", False))
            head = "미리보기" if getattr(args, "dry_run", False) else "등록 완료"
            print(f"[4/4] 스케줄러 {head}: 10분 인덱싱 + 매일 04:00 정제")
            for ln in lines:
                print("      " + ln.replace("\n", "\n      "))
        except Exception as e:  # 권한·환경 문제 시 수동 안내로 폴백
            print(f"[4/4] 스케줄러 자동 등록 실패({e}). 수동 등록은 AUTOMATION.md 참고.")

    # 5) 첫 백필 — 기본은 스케줄러에 맡기고, --index 면 지금 즉시 실행.
    if getattr(args, "index", False):
        print("\n첫 백필 시작 (임베딩 모델 ~2.2GB 최초 1회 다운로드 — 몇 분 걸릴 수 있음)…")
        cmd_index(argparse.Namespace(oldest_first=False, force=False))

    print("\n설정 완료! " + (
        "이제 검색할 수 있어요." if getattr(args, "index", False)
        else "스케줄러가 10분마다 자동으로 대화를 축적합니다(첫 실행 때 모델 ~2.2GB 다운로드)."))
    print("  검색:      mem \"검색어\"        (또는 vestige search ...)")
    print("  데스크탑 앱: vestige app        (네이티브 창 — 옵시디언처럼)")
    print("  웹 UI:      python -m vestige.web   →  http://127.0.0.1:8642")
    if not getattr(args, "index", False):
        print("  즉시 백필하려면:  vestige index   (안 해도 스케줄러가 알아서 채웁니다)")
    print("  설정 확인: vestige config")
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    """데스크탑 앱(네이티브 창)으로 검색 UI 실행."""
    try:
        from . import desktop
    except ImportError:
        print("데스크탑 앱은 pywebview가 필요합니다:  pip install \"vestige[desktop]\"")
        return 1
    try:
        desktop.run(port=args.port)
    except ImportError:
        print("pywebview 미설치. 설치:  pip install \"vestige[desktop]\"")
        return 1
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    """브라우저 웹 UI(FastAPI)를 실행 → http://127.0.0.1:8642."""
    from .web import main as web_main
    web_main()
    return 0


def cmd_scheduler(args: argparse.Namespace) -> int:
    from . import scheduler
    if args.action == "status":
        print(scheduler.status())
        return 0
    fn = scheduler.install if args.action == "install" else scheduler.uninstall
    lines = fn(dry_run=args.dry_run)
    verb = {"install": "등록", "uninstall": "제거"}[args.action]
    print(f"스케줄러 {verb}{' (미리보기)' if args.dry_run else ''}:")
    for ln in lines:
        print("  " + ln.replace("\n", "\n  "))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """세션 동기화 감시: Syncthing 충돌 사본을 superset-wins/fork로 해소(+선택 색인)."""
    from . import session_sync

    index_fn = (lambda: session_sync.default_index(log_fn=print)) if args.index else None
    if args.once:
        res = session_sync.sync_tick(index_fn=index_fn)
        for o in res.outcomes:
            extra = f" → fork {o.forked_to}" if o.forked_to else ""
            print(f"충돌 해소 {o.resolution}: {o.kept}{extra}")
        print(f"완료: 충돌 {len(res.outcomes)}건 해소" + (" · 색인 실행" if res.indexed else ""))
        return 0
    try:
        session_sync.watch(interval=args.interval, index_fn=index_fn)
    except KeyboardInterrupt:
        print("\n[sync] 중지")
    return 0


def cmd_syncthing(args: argparse.Namespace) -> int:
    """임베디드 Syncthing 자가점검 / 바이너리 갱신."""
    from . import syncthing
    if args.update:
        p = syncthing.update_binary(log_fn=print)
        print(f"갱신 완료: {p} (버전 {syncthing.SYNCTHING_VERSION})")
        return 0
    r = syncthing.self_check()
    print(f"\n결과: ready={r['ready']} · device_id={r['device_id']} · gui={r['gui']}")
    return 0 if r["ready"] else 1


def main(argv: list[str] | None = None) -> int:
    # 콘솔 진입점(vestige/mem)은 main()을 인자 없이 호출 → sys.argv에서 직접 취함.
    if argv is None:
        argv = sys.argv[1:]
    # pythonw.exe(콘솔 없음, 스케줄 작업)에선 표준 스트림이 None → print 크래시 방지.
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    # 출력을 utf-8로 강제 → cp949 콘솔의 인코딩 크래시·한글 깨짐 방지.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    p = argparse.ArgumentParser(prog="vestige", description="대화 정보자산 검색")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="의미 검색")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--session", default=None, help="세션ID 접두 또는 프로젝트 부분일치")
    s.add_argument("--since", default=None, help="이 날짜 이후 (예: 2026-07-01)")
    s.add_argument("--until", default=None, help="이 날짜 이전 (예: 2026-07-24, 그날 포함)")
    s.add_argument("--semantic-only", action="store_true", help="키워드(BM25) 없이 의미검색만")
    s.set_defaults(func=cmd_search)

    i = sub.add_parser("index", help="백필/증분 인덱싱")
    i.add_argument("--oldest-first", action="store_true", help="과거부터(기본은 최근부터)")
    i.add_argument("--force", action="store_true", help="메모리 가드 무시하고 강제 실행")
    i.set_defaults(func=cmd_index)

    en = sub.add_parser("enrich", help="세션 요약·태그 정제(claude -p / API / off)")
    en.add_argument("--backend",
                    choices=["claude", "anthropic", "openai", "gemini", "ollama", "off"],
                    default=None,
                    help="정제 백엔드 (기본: VESTIGE_ENRICH_BACKEND, 없으면 claude)")
    en.add_argument("--model", default=None, help="모델 (미지정 시 백엔드별 기본값)")
    en.add_argument("--session", default=None, help="특정 세션만")
    en.add_argument("--limit", type=int, default=None, help="세션 수 제한(테스트용)")
    en.add_argument("--all", action="store_true", help="이미 정제된 것도 재정제")
    en.set_defaults(func=cmd_enrich)

    pr = sub.add_parser("progress", help="백필 진행률")
    pr.set_defaults(func=cmd_progress)

    cf = sub.add_parser("config", help="현재 유효 설정·설정 파일 위치 확인")
    cf.set_defaults(func=cmd_config)

    se = sub.add_parser("setup", help="최초 온보딩(폴더·설정 생성 + 스케줄러 등록)")
    se.add_argument("--no-scheduler", action="store_true", help="스케줄러 자동 등록 생략")
    se.add_argument("--dry-run", action="store_true", help="스케줄러 등록 미리보기(실행 안 함)")
    se.set_defaults(func=cmd_setup)

    ap = sub.add_parser("app", help="데스크탑 앱(네이티브 창)으로 실행")
    ap.add_argument("--port", type=int, default=None, help="로컬 포트(기본 8642, 사용중이면 자동)")
    ap.set_defaults(func=cmd_app)

    sc = sub.add_parser("scheduler", help="자동 축적 스케줄러 등록/제거/상태")
    sc.add_argument("action", choices=["install", "uninstall", "status"])
    sc.add_argument("--dry-run", action="store_true", help="실행 없이 계획만 출력")
    sc.set_defaults(func=cmd_scheduler)

    rc = sub.add_parser("reconcile", help="원문 없는 고아 벡터 정리")
    rc.set_defaults(func=cmd_reconcile)

    st = sub.add_parser("stats", help="현황")
    st.set_defaults(func=cmd_stats)

    wb = sub.add_parser("web", help="브라우저 웹 UI 실행 (http://127.0.0.1:8642)")
    wb.set_defaults(func=cmd_web)

    sy = sub.add_parser("sync", help="세션 동기화 감시(Syncthing 충돌 해소 + 선택 색인)")
    sy.add_argument("--once", action="store_true", help="한 번만 점검하고 종료")
    sy.add_argument("--interval", type=float, default=10.0, help="점검 간격(초, 기본 10)")
    sy.add_argument("--index", action="store_true", help="동기 직후 증분 색인도 실행(스케줄러 미사용 시)")
    sy.set_defaults(func=cmd_sync)

    st = sub.add_parser("syncthing", help="임베디드 Syncthing 자가점검(바이너리 확보+기동+Device ID)")
    st.add_argument("--update", action="store_true", help="번들 바이너리를 지정 버전으로 다시 받음")
    st.set_defaults(func=cmd_syncthing)

    # `mem "질의"` 처럼 서브커맨드 생략 시 검색으로 간주:
    # 첫 토큰이 플래그도 아니고 알려진 서브커맨드도 아니면 앞에 'search'를 붙인다.
    known = set(sub.choices)
    if argv and not argv[0].startswith("-") and argv[0] not in known:
        argv = ["search", *argv]

    args = p.parse_args(argv)
    if args.cmd is None:
        p.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
