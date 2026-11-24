"""Estimate periods.

Crowdfunding estimates are rarely a day. They are "Oct 2026", "Q4 2026" or
just "2027". An estimate is stored as one of:

    YYYY          a year
    YYYY-Qn       a quarter (n = 1..4)
    YYYY-MM       a month
    YYYY-MM-DD    a day

A project is overdue once the *end* of its period has passed.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

_YEAR = re.compile(r"^(\d{4})$")
_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_DAY = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def period_end(period: str) -> date:
    """Last day covered by the period. Raises ValueError if malformed."""
    if m := _YEAR.match(period):
        return date(int(m[1]), 12, 31)
    if m := _QUARTER.match(period):
        year, month = int(m[1]), int(m[2]) * 3
        return date(year, month, calendar.monthrange(year, month)[1])
    if m := _MONTH.match(period):
        year, month = int(m[1]), int(m[2])
        return date(year, month, calendar.monthrange(year, month)[1])
    if m := _DAY.match(period):
        return date(int(m[1]), int(m[2]), int(m[3]))
    raise ValueError(f"not a valid estimate period: {period!r} (use YYYY, YYYY-Qn, YYYY-MM or YYYY-MM-DD)")


def validate_period(period: str | None) -> str | None:
    if period is None:
        return None
    period = period.strip().upper()
    if not period:
        return None
    period_end(period)
    return period


def period_label(period: str | None) -> str | None:
    """Human label: '2026-10' -> 'Oct 2026', '2026-Q4' -> 'Q4 2026'."""
    if not period:
        return None
    if m := _QUARTER.match(period):
        return f"Q{m[2]} {m[1]}"
    if m := _MONTH.match(period):
        return f"{_MONTH_NAMES[int(m[2]) - 1]} {m[1]}"
    if m := _DAY.match(period):
        return f"{_MONTH_NAMES[int(m[2]) - 1]} {int(m[3])}, {m[1]}"
    return period


def months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)
