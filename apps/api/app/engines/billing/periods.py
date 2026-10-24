"""Billing periods.

Half-yearly and yearly follow the **Indian financial year** (April–March), which
is what societies actually use. Quarters are calendar quarters, which is also
what they use — the two conventions genuinely differ in Indian practice, so both
are implemented rather than forced into one.

Pure functions over dates. No database, no clock.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class BillingFrequency(StrEnum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    HALF_YEARLY = "HALF_YEARLY"
    YEARLY = "YEARLY"
    ONE_TIME = "ONE_TIME"


MONTHS_IN = {
    BillingFrequency.MONTHLY: 1,
    BillingFrequency.QUARTERLY: 3,
    BillingFrequency.HALF_YEARLY: 6,
    BillingFrequency.YEARLY: 12,
    BillingFrequency.ONE_TIME: 1,
}

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_SHORT = tuple(m[:3] for m in _MONTH_NAMES)


@dataclass(frozen=True, slots=True)
class BillingPeriod:
    frequency: BillingFrequency
    key: str
    """Stable identifier, unique per (flat, template). ``2026-08``, ``2026-Q3``,
    ``2026-H1``, ``FY2026-27``."""
    label: str
    start: date
    end: date

    @property
    def months(self) -> int:
        return MONTHS_IN[self.frequency]

    def due_date(self, days: int) -> date:
        return self.end + timedelta(days=days)

    def as_dict(self) -> dict[str, str]:
        return {
            "frequency": self.frequency.value,
            "key": self.key,
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


def _end_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def financial_year_start(on: date, fy_start_month: int = 4) -> date:
    """First day of the financial year containing ``on``.

    With the default April start, 2026-02-15 belongs to FY 2025-26, which begins
    on 2025-04-01.
    """
    year = on.year if on.month >= fy_start_month else on.year - 1
    return date(year, fy_start_month, 1)


def financial_year_label(start: date) -> str:
    """``FY2026-27`` for a year beginning in April 2026."""
    if start.month == 1:
        return f"FY{start.year}"
    return f"FY{start.year}-{str(start.year + 1)[-2:]}"


def period_for(
    frequency: BillingFrequency,
    on: date,
    *,
    fy_start_month: int = 4,
    one_time_key: str | None = None,
) -> BillingPeriod:
    """The billing period containing ``on``."""
    match frequency:
        case BillingFrequency.MONTHLY:
            start = date(on.year, on.month, 1)
            end = _end_of_month(on.year, on.month)
            return BillingPeriod(
                frequency,
                f"{on.year:04d}-{on.month:02d}",
                f"{_MONTH_NAMES[on.month - 1]} {on.year}",
                start,
                end,
            )

        case BillingFrequency.QUARTERLY:
            quarter = (on.month - 1) // 3 + 1
            first = (quarter - 1) * 3 + 1
            last = first + 2
            start = date(on.year, first, 1)
            end = _end_of_month(on.year, last)
            return BillingPeriod(
                frequency,
                f"{on.year:04d}-Q{quarter}",
                f"Q{quarter} {on.year} ({_SHORT[first - 1]}–{_SHORT[last - 1]})",
                start,
                end,
            )

        case BillingFrequency.HALF_YEARLY:
            fy_start = financial_year_start(on, fy_start_month)
            months_in = (on.year - fy_start.year) * 12 + (on.month - fy_start.month)
            half = 1 if months_in < 6 else 2
            start = _add_months(fy_start, 0 if half == 1 else 6)
            end = _add_months(start, 6) - timedelta(days=1)
            return BillingPeriod(
                frequency,
                f"{fy_start.year:04d}-H{half}",
                f"H{half} {financial_year_label(fy_start)} "
                f"({_SHORT[start.month - 1]}–{_SHORT[end.month - 1]})",
                start,
                end,
            )

        case BillingFrequency.YEARLY:
            fy_start = financial_year_start(on, fy_start_month)
            end = _add_months(fy_start, 12) - timedelta(days=1)
            label = financial_year_label(fy_start)
            return BillingPeriod(frequency, label, label.replace("FY", "FY "), fy_start, end)

        case BillingFrequency.ONE_TIME:
            key = one_time_key or f"OT-{on.isoformat()}"
            return BillingPeriod(
                frequency, key, f"One-time ({on.strftime('%d %b %Y')})", on, on
            )

        case _:  # pragma: no cover - the enum is closed
            raise ValueError(f"Unsupported frequency {frequency}")


def next_period(period: BillingPeriod, *, fy_start_month: int = 4) -> BillingPeriod:
    """The period immediately after this one."""
    if period.frequency is BillingFrequency.ONE_TIME:
        raise ValueError("A one-time period has no successor")
    return period_for(
        period.frequency, period.end + timedelta(days=1), fy_start_month=fy_start_month
    )


def previous_period(period: BillingPeriod, *, fy_start_month: int = 4) -> BillingPeriod:
    if period.frequency is BillingFrequency.ONE_TIME:
        raise ValueError("A one-time period has no predecessor")
    return period_for(
        period.frequency, period.start - timedelta(days=1), fy_start_month=fy_start_month
    )


def recent_periods(
    frequency: BillingFrequency, on: date, count: int = 6, *, fy_start_month: int = 4
) -> list[BillingPeriod]:
    """This period and the ``count - 1`` before it, oldest first.

    Used to offer an admin a period to bill without making them type a key.
    """
    if frequency is BillingFrequency.ONE_TIME:
        return [period_for(frequency, on, fy_start_month=fy_start_month)]

    periods = [period_for(frequency, on, fy_start_month=fy_start_month)]
    for _ in range(max(count - 1, 0)):
        periods.append(previous_period(periods[-1], fy_start_month=fy_start_month))
    return list(reversed(periods))


def parse_key(key: str, *, fy_start_month: int = 4) -> BillingPeriod:
    """Reconstruct a period from its key, for reading historical bills."""
    import re

    if m := re.fullmatch(r"(\d{4})-(\d{2})", key):
        return period_for(
            BillingFrequency.MONTHLY, date(int(m[1]), int(m[2]), 1), fy_start_month=fy_start_month
        )
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", key):
        return period_for(
            BillingFrequency.QUARTERLY,
            date(int(m[1]), (int(m[2]) - 1) * 3 + 1, 1),
            fy_start_month=fy_start_month,
        )
    if m := re.fullmatch(r"(\d{4})-H([12])", key):
        fy_start = date(int(m[1]), fy_start_month, 1)
        anchor = _add_months(fy_start, 0 if m[2] == "1" else 6)
        return period_for(
            BillingFrequency.HALF_YEARLY, anchor, fy_start_month=fy_start_month
        )
    if m := re.fullmatch(r"FY(\d{4})(?:-\d{2})?", key):
        return period_for(
            BillingFrequency.YEARLY,
            date(int(m[1]), fy_start_month, 1),
            fy_start_month=fy_start_month,
        )
    if key.startswith("OT-"):
        raise ValueError("A one-time period cannot be reconstructed from its key alone")
    raise ValueError(f"Unrecognised period key: {key!r}")
