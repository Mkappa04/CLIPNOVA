from datetime import date, timedelta

from backend.models.entities import RightsRecord
from backend.rights_management.policy import Purpose, evaluate


def rec(**kw) -> RightsRecord:
    base = dict(owner="Creator", source_url="", license_type="creator_permission",
                authorization_status="authorized", commercial_use_allowed=True,
                attribution_required=True, attribution_text="Clip by @creator", expires_at=None,
                restrictions="", evidence="email 2026-11-01")
    base.update(kw)
    return RightsRecord(**base)


def test_internal_always_allowed():
    assert evaluate(None, Purpose.INTERNAL).allowed


def test_missing_record_blocks_export():
    d = evaluate(None, Purpose.NON_COMMERCIAL)
    assert not d.allowed and d.blockers


def test_fully_authorized_commercial_allowed():
    d = evaluate(rec(), Purpose.COMMERCIAL)
    assert d.allowed, d.blockers


def test_credit_only_is_not_authorization():
    d = evaluate(rec(license_type="credit_only"), Purpose.NON_COMMERCIAL)
    assert not d.allowed
    assert any("non è un'autorizzazione" in b for b in d.blockers)


def test_unknown_license_and_pending_status_block():
    d = evaluate(rec(license_type="unknown", authorization_status="pending"), Purpose.NON_COMMERCIAL)
    assert not d.allowed and len(d.blockers) == 2


def test_nc_license_blocks_commercial_only():
    r = rec(license_type="cc_by_nc", commercial_use_allowed=True)
    assert not evaluate(r, Purpose.COMMERCIAL).allowed
    assert evaluate(r, Purpose.NON_COMMERCIAL).allowed


def test_commercial_flag_required():
    r = rec(commercial_use_allowed=False)
    assert not evaluate(r, Purpose.COMMERCIAL).allowed
    assert evaluate(r, Purpose.NON_COMMERCIAL).allowed


def test_expired_blocks_and_soon_warns():
    today = date(2026, 11, 14)
    assert not evaluate(rec(expires_at=today - timedelta(days=1)), Purpose.NON_COMMERCIAL, today).allowed
    d = evaluate(rec(expires_at=today + timedelta(days=3)), Purpose.NON_COMMERCIAL, today)
    assert d.allowed and any("scade a breve" in w for w in d.warnings)


def test_attribution_text_required_when_needed():
    assert not evaluate(rec(attribution_text=""), Purpose.NON_COMMERCIAL).allowed
    assert evaluate(rec(attribution_required=False, attribution_text=""), Purpose.NON_COMMERCIAL).allowed
    # CC-BY always needs attribution even if the flag is off
    assert not evaluate(rec(license_type="cc_by", attribution_required=False, attribution_text=""),
                        Purpose.NON_COMMERCIAL).allowed


def test_restrictions_produce_warning():
    d = evaluate(rec(restrictions="No TikTok"), Purpose.NON_COMMERCIAL)
    assert d.allowed and any("No TikTok" in w for w in d.warnings)
