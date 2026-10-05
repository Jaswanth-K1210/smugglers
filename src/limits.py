"""Search request limits: box size and time period. Standard library only.

Kept free of numpy / pandas / rasterio so the web server (Render, 512 MB) can check a
request without loading the image-processing stack; src.search re-exports these.
"""
import math
from datetime import date, datetime, timedelta, timezone

MIN_KM, MAX_KM = 11, 60                 # one 1024 px tile ... the free-CPU time budget
MAX_PERIOD_DAYS, MAX_PASSES = 31, 6     # time-period search (docs/DEPLOYMENT_PLAN.md §2)
DEFAULT_DAYS = 12                       # no dates given: the last 12 days (Sentinel-1 revisit ~6 days)
ARCHIVE_START = date(2014, 10, 3)       # first Sentinel-1 IW data on Planetary Computer


def box_km(box):
    lon0, lat0, lon1, lat1 = box
    return ((lon1 - lon0) * 111.32 * math.cos(math.radians((lat0 + lat1) / 2)), (lat1 - lat0) * 110.57)


def validate(box):
    """(west, south, east, north) as floats; ValueError with a sentence a user can act on."""
    if len(box) != 4:
        raise ValueError("Send the box as [west, south, east, north].")
    lon0, lat0, lon1, lat1 = map(float, box)
    if not (-180 <= lon0 < lon1 <= 180 and -85 <= lat0 < lat1 <= 85):
        raise ValueError("The box corners are out of order or off the map.")
    w, h = box_km(box)
    if min(w, h) < MIN_KM:
        raise ValueError(f"Draw a box at least {MIN_KM} km on each side (this one is {w:.0f} × {h:.0f} km).")
    if max(w, h) > MAX_KM:
        raise ValueError(f"Draw a box at most {MAX_KM} km on each side (this one is {w:.0f} × {h:.0f} km).")
    return lon0, lat0, lon1, lat1


def _day(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def validate_period(start, end, today=None):
    """(start, end) as dates; ValueError with a sentence a user can act on."""
    try:
        a, b = _day(start), _day(end)
    except (ValueError, TypeError):
        raise ValueError("Send the dates as YYYY-MM-DD.")
    today = _day(today) if today else datetime.now(timezone.utc).date()
    if b < a:
        raise ValueError("The end date is before the start date.")
    if b > today:
        raise ValueError("The end date is in the future.")
    if a < ARCHIVE_START:
        raise ValueError(f"Sentinel-1 images start on {ARCHIVE_START:%d %b %Y}; pick a later start date.")
    if (b - a).days + 1 > MAX_PERIOD_DAYS:
        raise ValueError(f"Pick a period of at most {MAX_PERIOD_DAYS} days (this one is {(b - a).days + 1}).")
    return a, b


def default_period(today=None):
    """The period used when the user gives no dates: the last DEFAULT_DAYS days."""
    b = _day(today) if today else datetime.now(timezone.utc).date()
    return b - timedelta(days=DEFAULT_DAYS - 1), b
