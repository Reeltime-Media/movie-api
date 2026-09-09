from app.services.bakong import nbc_reports_paid
from app.services.bakong_check_cache import ttl_for_check


def test_nbc_reports_paid_accepts_int_and_string_zero():
    assert nbc_reports_paid({"responseCode": 0}) is True
    assert nbc_reports_paid({"responseCode": "0"}) is True
    assert nbc_reports_paid({"responseCode": "00"}) is True
    assert nbc_reports_paid({"responseCode": 1, "errorCode": 1}) is False
    assert nbc_reports_paid(None) is False
    assert nbc_reports_paid({}) is False


def test_ttl_for_check_backs_off_rate_limits():
    assert ttl_for_check(paid=True) == 60.0
    assert ttl_for_check(paid=False) == 8.0
    assert ttl_for_check(paid=False, rate_limited=True) == 120.0


def test_unknown_status_is_not_treated_as_paid():
    from app.services.bakong_check_cache import (
        STATUS_UNKNOWN,
        get_cached_md5_paid,
        set_cached_md5_status,
    )

    set_cached_md5_status("abc-unknown", STATUS_UNKNOWN, ttl=30)
    assert get_cached_md5_paid("abc-unknown") is False
