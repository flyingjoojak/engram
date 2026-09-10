"""CSRF 가드: Host 루프백 검증(리바인딩) + 상태변경 cross/same-site 차단 + Origin 폴백."""
from vestige.web import _csrf_blocked, _host_of


# ── _host_of ──────────────────────────────────────────────────
def test_host_of_extracts_hostname():
    assert _host_of("127.0.0.1:8642") == "127.0.0.1"
    assert _host_of("localhost") == "localhost"
    assert _host_of("[::1]:8642") == "::1"
    assert _host_of("http://evil.com:9/x") == "evil.com"
    assert _host_of("HTTP://Evil.COM") == "evil.com"
    assert _host_of(None) is None


# ── 안전 메서드 ───────────────────────────────────────────────
def test_safe_methods_pass_when_host_ok():
    for site in (None, "cross-site", "same-origin", "same-site", "none"):
        assert _csrf_blocked("GET", site, host="127.0.0.1:8642") is False
    assert _csrf_blocked("GET", "cross-site") is False   # host 미검증(테스트 편의)


# ── Host 검증(모든 메서드) — DNS 리바인딩 봉쇄 ────────────────
def test_bad_host_blocked_even_for_get():
    assert _csrf_blocked("GET", "same-origin", host="evil.com:8642") is True
    assert _csrf_blocked("POST", "same-origin", host="evil.com") is True
    assert _csrf_blocked("GET", None, host="127.0.0.1:8642") is False
    assert _csrf_blocked("GET", None, host="localhost:8642") is False


# ── 상태변경 메서드: site 판정 ────────────────────────────────
def test_mutating_cross_and_same_site_blocked():
    for m in ("POST", "PUT", "DELETE", "PATCH", "post"):
        assert _csrf_blocked(m, "cross-site", host="127.0.0.1") is True
    assert _csrf_blocked("POST", "same-site", host="127.0.0.1") is True   # 루프백 다른 포트도 불허


def test_mutating_same_origin_and_none_allowed():
    assert _csrf_blocked("POST", "same-origin", host="127.0.0.1:8642") is False
    assert _csrf_blocked("POST", "none", host="127.0.0.1:8642") is False


# ── Origin 폴백(구형 브라우저: Sec-Fetch-Site 없음) ──────────
def test_origin_fallback_when_no_sec_fetch_site():
    # 헤더 없음 + Origin 있음 → 오리진이 루프백 아니면 차단, 맞으면 허용
    assert _csrf_blocked("POST", None, host="127.0.0.1:8642", origin="http://evil.com") is True
    assert _csrf_blocked("POST", None, host="127.0.0.1:8642", origin="http://127.0.0.1:8642") is False
    # 둘 다 없음(CLI·테스트·사이드카) → 허용
    assert _csrf_blocked("POST", None, host="127.0.0.1:8642", origin=None) is False
