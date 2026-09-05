"""Deal health threshold tests (PRD B9, Locked Business Rules #9).

Pure logic only: `is_stalled`, `discount_anomaly`, `delivery_slippage` and
`effective_discount_percent` take plain values and return plain values.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.services.dealhealth import (
    DISCOUNT_ANOMALY_THRESHOLD_POINTS,
    STALLED_THRESHOLD_DAYS,
    delivery_slippage,
    discount_anomaly,
    effective_discount_percent,
    is_stalled,
)

NOW = datetime(2026, 9, 6, tzinfo=UTC)


def test_stalled_threshold_is_seven_days() -> None:
    assert STALLED_THRESHOLD_DAYS == 7


def test_exactly_at_threshold_is_stalled() -> None:
    last_activity = datetime(2026, 8, 30, tzinfo=UTC)  # exactly 7 days before NOW
    flagged, days = is_stalled(last_activity, now=NOW)
    assert flagged
    assert days == 7


def test_one_day_short_of_threshold_is_not_stalled() -> None:
    last_activity = datetime(2026, 8, 31, tzinfo=UTC)  # 6 days before NOW
    flagged, days = is_stalled(last_activity, now=NOW)
    assert not flagged
    assert days == 6


def test_activity_today_is_never_stalled() -> None:
    flagged, days = is_stalled(NOW, now=NOW)
    assert not flagged
    assert days == 0


def test_effective_discount_percent_basic() -> None:
    # 2000 subtotal, 400 discount -> 20%
    assert effective_discount_percent(Decimal("2000"), Decimal("400")) == Decimal("20.00")


def test_effective_discount_percent_zero_subtotal_is_zero_not_a_crash() -> None:
    assert effective_discount_percent(Decimal("0"), Decimal("0")) == Decimal("0")


def test_anomaly_threshold_is_ten_points() -> None:
    assert DISCOUNT_ANOMALY_THRESHOLD_POINTS == Decimal("10")


def test_no_rep_history_is_never_an_anomaly() -> None:
    """A rep's very first non-draft quotation has no baseline - not treated
    as an anomaly against a fabricated zero average."""
    flagged, delta = discount_anomaly(Decimal("50"), None)
    assert not flagged
    assert delta == Decimal("0")


def test_exactly_ten_points_over_is_not_yet_an_anomaly() -> None:
    """Strictly greater than the threshold, not at it."""
    flagged, delta = discount_anomaly(Decimal("18"), Decimal("8"))
    assert not flagged
    assert delta == Decimal("10.00")


def test_eleven_points_over_is_an_anomaly() -> None:
    flagged, delta = discount_anomaly(Decimal("19"), Decimal("8"))
    assert flagged
    assert delta == Decimal("11.00")


def test_discount_below_average_is_not_an_anomaly() -> None:
    flagged, delta = discount_anomaly(Decimal("5"), Decimal("8"))
    assert not flagged
    assert delta == Decimal("-3.00")


def test_no_promised_date_is_never_slipped() -> None:
    flagged, days = delivery_slippage(None, today=date(2026, 9, 6))
    assert not flagged
    assert days == 0


def test_promised_date_today_is_not_yet_slipped() -> None:
    flagged, days = delivery_slippage(date(2026, 9, 6), today=date(2026, 9, 6))
    assert not flagged
    assert days == 0


def test_promised_date_in_the_past_has_slipped() -> None:
    flagged, days = delivery_slippage(date(2026, 9, 1), today=date(2026, 9, 6))
    assert flagged
    assert days == 5


def test_promised_date_in_the_future_has_not_slipped() -> None:
    flagged, days = delivery_slippage(date(2026, 9, 10), today=date(2026, 9, 6))
    assert not flagged
    assert days == 0
