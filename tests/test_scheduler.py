"""스케줄러 순수 로직 테스트 (실제 시스템 등록 없이 dry-run/문자열 처리만)."""

from __future__ import annotations

from vestige import scheduler as S


def test_platform_dispatch_dry_run_no_side_effects():
    # dry_run은 계획 문자열만 반환하고 시스템을 건드리지 않아야.
    lines = S.install(dry_run=True)
    assert isinstance(lines, list) and lines


def test_cron_block_has_both_jobs():
    b = S._cron_block()
    assert f"*/{S.INDEX_EVERY_MIN} * * * *" in b        # 10분 인덱싱
    assert f"{S.ENRICH_MIN} {S.ENRICH_HOUR} * * *" in b  # 04:00 정제
    assert "-m vestige index" in b and "-m vestige enrich" in b


def test_cron_block_has_sync_job():
    b = S._cron_block()
    assert "-m vestige sync --once" in b               # 세션 동기화 충돌 해소(주기)


def test_mac_jobs_include_sync():
    labels = [label for label, _args, _when in S._mac_jobs()]
    assert "com.vestige.sync" in labels


def test_cron_strip_is_idempotent():
    existing = "0 0 * * * echo hi\n"
    injected = existing + "\n" + S._cron_block()
    stripped = S._cron_strip(injected)
    # 관리블록만 제거되고 사용자 crontab은 보존
    assert "echo hi" in stripped
    assert S._CRON_BEGIN not in stripped
    # 다시 넣었다 빼도 원본과 동일(중복 누적 없음)
    reinjected = (stripped + "\n\n" + S._cron_block())
    assert S._cron_strip(reinjected).count("echo hi") == 1


def test_mac_plist_shapes():
    p_int = S._mac_plist("com.vestige.index", ["py", "-m", "vestige", "index"], interval=600)
    assert "StartInterval" in p_int and "<integer>600</integer>" in p_int
    p_cal = S._mac_plist("com.vestige.enrich", ["py", "-m", "vestige", "enrich"], hour=4, minute=0)
    assert "StartCalendarInterval" in p_cal and "<integer>4</integer>" in p_cal
