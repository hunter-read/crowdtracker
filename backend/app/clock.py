"""The one place that decides what "today" is.

The container usually runs in UTC, so dates are computed in CROWDTRACKER_TZ
(falling back to TZ) to match the person using the app.
"""

from __future__ import annotations

import os
from datetime import date, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def local_zone() -> tzinfo | None:
    name = os.environ.get("CROWDTRACKER_TZ") or os.environ.get("TZ")
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def today() -> date:
    zone = local_zone()
    return datetime.now(zone).date() if zone else date.today()


def local_date(moment: datetime) -> date:
    """The calendar day `moment` falls on in the configured zone."""
    zone = local_zone()
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(zone).date() if zone else moment.astimezone().date()
