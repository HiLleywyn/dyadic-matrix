"""Portable wall-clock calculation shared with the Dyadic schedule contract."""
import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_ZONE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+){0,2}$")
def _now(value=None): return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)

def zone_name(value: Any) -> str | None:
    """An IANA time zone name this server knows, or None."""
    name = str(value or "").strip()
    if not name or len(name) > 64 or not _ZONE.match(name):
        return None
    try:
        ZoneInfo(name)
    except (ValueError, OSError, KeyError):
        return None
    return name

def _on(cadence: dict, day: date) -> bool:
    every = cadence["every"]
    if every == "week":
        return DAYS[day.weekday()] in cadence["days"]
    if every == "month":
        return day.day == min(int(cadence["day"]), calendar.monthrange(day.year, day.month)[1])
    return True

def next_run(cadence: dict, zone: str, after: datetime) -> datetime:
    """The first time strictly after ``after`` the cadence runs, in UTC."""
    tz = ZoneInfo(zone)
    after = _now(after)
    if cadence["every"] == "hour":
        # Minute by minute in UTC, so every real hour counts once, whatever
        # the zone's offset (half-hour zones included) or a change of clocks.
        moment = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(3 * 60):
            if moment.astimezone(tz).minute == int(cadence["minute"]):
                return moment
            moment += timedelta(minutes=1)
        raise ValueError("no run within three hours")
    hour, minute = (int(part) for part in cadence["time"].split(":"))
    first = after.astimezone(tz).date()
    for offset in range(0, 800):
        day = first + timedelta(days=offset)
        if not _on(cadence, day):
            continue
        # fold=0: a time the clocks skip runs that much later; one they repeat, the first time.
        moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(timezone.utc)
        if moment > after:
            return moment
    raise ValueError("no run within two years")
