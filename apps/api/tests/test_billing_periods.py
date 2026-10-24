"""Billing periods — Indian financial year semantics.

Pure. Half-yearly and yearly follow April–March; quarters are calendar
quarters. Both conventions are genuinely used in Indian societies, and getting
either wrong bills the wrong months.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.engines.billing.periods import (
    BillingFrequency,
    financial_year_label,
    financial_year_start,
    next_period,
    parse_key,
    period_for,
    previous_period,
    recent_periods,
)


@pytest.mark.parametrize(
    "on,key,start,end",
    [
        (date(2026, 8, 23), "2026-08", date(2026, 8, 1), date(2026, 8, 31)),
        (date(2026, 2, 14), "2026-02", date(2026, 2, 1), date(2026, 2, 28)),
        (date(2024, 2, 14), "2024-02", date(2024, 2, 1), date(2024, 2, 29)),  # leap year
        (date(2026, 12, 31), "2026-12", date(2026, 12, 1), date(2026, 12, 31)),
    ],
)
def test_monthly(on: date, key: str, start: date, end: date) -> None:
    p = period_for(BillingFrequency.MONTHLY, on)
    assert (p.key, p.start, p.end) == (key, start, end)
    assert p.months == 1


@pytest.mark.parametrize(
    "on,key,start,end",
    [
        (date(2026, 1, 15), "2026-Q1", date(2026, 1, 1), date(2026, 3, 31)),
        (date(2026, 8, 23), "2026-Q3", date(2026, 7, 1), date(2026, 9, 30)),
        (date(2026, 12, 31), "2026-Q4", date(2026, 10, 1), date(2026, 12, 31)),
    ],
)
def test_quarterly_uses_calendar_quarters(on: date, key: str, start: date, end: date) -> None:
    p = period_for(BillingFrequency.QUARTERLY, on)
    assert (p.key, p.start, p.end) == (key, start, end)
    assert p.months == 3


@pytest.mark.parametrize(
    "on,key,start,end",
    [
        # April–September is H1 of the financial year that starts that April.
        (date(2026, 4, 1), "2026-H1", date(2026, 4, 1), date(2026, 9, 30)),
        (date(2026, 8, 23), "2026-H1", date(2026, 4, 1), date(2026, 9, 30)),
        (date(2026, 9, 30), "2026-H1", date(2026, 4, 1), date(2026, 9, 30)),
        # October–March is H2 — and January to March belongs to the *previous*
        # April's financial year, which is the boundary most often got wrong.
        (date(2026, 10, 1), "2026-H2", date(2026, 10, 1), date(2027, 3, 31)),
        (date(2027, 2, 15), "2026-H2", date(2026, 10, 1), date(2027, 3, 31)),
        (date(2027, 3, 31), "2026-H2", date(2026, 10, 1), date(2027, 3, 31)),
    ],
)
def test_half_yearly_follows_the_indian_financial_year(
    on: date, key: str, start: date, end: date
) -> None:
    p = period_for(BillingFrequency.HALF_YEARLY, on)
    assert (p.key, p.start, p.end) == (key, start, end)
    assert p.months == 6


@pytest.mark.parametrize(
    "on,key,start,end",
    [
        (date(2026, 4, 1), "FY2026-27", date(2026, 4, 1), date(2027, 3, 31)),
        (date(2026, 8, 23), "FY2026-27", date(2026, 4, 1), date(2027, 3, 31)),
        (date(2027, 3, 31), "FY2026-27", date(2026, 4, 1), date(2027, 3, 31)),
        # 1 April flips the year.
        (date(2027, 4, 1), "FY2027-28", date(2027, 4, 1), date(2028, 3, 31)),
        # February belongs to the financial year that began the previous April.
        (date(2026, 2, 15), "FY2025-26", date(2025, 4, 1), date(2026, 3, 31)),
    ],
)
def test_yearly_follows_the_indian_financial_year(
    on: date, key: str, start: date, end: date
) -> None:
    p = period_for(BillingFrequency.YEARLY, on)
    assert (p.key, p.start, p.end) == (key, start, end)
    assert p.months == 12


def test_financial_year_start_and_label() -> None:
    assert financial_year_start(date(2026, 3, 31)) == date(2025, 4, 1)
    assert financial_year_start(date(2026, 4, 1)) == date(2026, 4, 1)
    assert financial_year_label(date(2026, 4, 1)) == "FY2026-27"
    assert financial_year_label(date(2025, 4, 1)) == "FY2025-26"


def test_a_society_can_use_a_january_financial_year() -> None:
    """Not the Indian default, but the column exists so it must work."""
    p = period_for(BillingFrequency.YEARLY, date(2026, 8, 23), fy_start_month=1)
    assert p.start == date(2026, 1, 1)
    assert p.end == date(2026, 12, 31)


def test_next_and_previous() -> None:
    august = period_for(BillingFrequency.MONTHLY, date(2026, 8, 15))
    assert next_period(august).key == "2026-09"
    assert previous_period(august).key == "2026-07"

    december = period_for(BillingFrequency.MONTHLY, date(2026, 12, 15))
    assert next_period(december).key == "2027-01"

    q4 = period_for(BillingFrequency.QUARTERLY, date(2026, 11, 1))
    assert next_period(q4).key == "2027-Q1"

    h2 = period_for(BillingFrequency.HALF_YEARLY, date(2026, 11, 1))
    assert previous_period(h2).key == "2026-H1"


def test_recent_periods_are_oldest_first() -> None:
    periods = recent_periods(BillingFrequency.MONTHLY, date(2026, 8, 15), 6)
    assert [p.key for p in periods] == [
        "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
    ]


@pytest.mark.parametrize(
    "key,frequency",
    [
        ("2026-08", BillingFrequency.MONTHLY),
        ("2026-Q3", BillingFrequency.QUARTERLY),
        ("2026-H1", BillingFrequency.HALF_YEARLY),
        ("FY2026-27", BillingFrequency.YEARLY),
    ],
)
def test_keys_round_trip(key: str, frequency: BillingFrequency) -> None:
    """A key stored on a years-old bill must still resolve to the same dates."""
    parsed = parse_key(key)
    assert parsed.frequency is frequency
    assert parsed.key == key


@pytest.mark.parametrize("key", ["nonsense", "2026-13", "2026-Q5", "2026-H3", ""])
def test_bad_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        parse_key(key)


def test_due_date() -> None:
    p = period_for(BillingFrequency.MONTHLY, date(2026, 8, 15))
    assert p.due_date(15) == date(2026, 9, 15)


def test_one_time_has_no_neighbours() -> None:
    p = period_for(BillingFrequency.ONE_TIME, date(2026, 8, 15))
    assert p.start == p.end == date(2026, 8, 15)
    with pytest.raises(ValueError):
        next_period(p)


def test_billing_frequency_is_a_single_enum() -> None:
    """Two enums with the same members compare unequal by identity — which
    silently broke the period/template frequency check once already."""
    from app.models.tenant.enums import BillingFrequency as ModelFrequency

    assert ModelFrequency is BillingFrequency
