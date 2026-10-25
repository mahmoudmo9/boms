"""Time source for the parties module. "Today" is the PC's local date (same zone as the backup scheduler).

Tests replace ``now`` and ``local_tz`` to pin the clock and the zone.
"""

from datetime import date, datetime, tzinfo

from app.core.time import utcnow


def now() -> datetime:
    return utcnow()


def local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo


def today() -> date:
    return now().astimezone(local_tz()).date()
