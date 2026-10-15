"""Parse the timestamp spellings used by backup notification mail."""

from __future__ import annotations

import re
from datetime import datetime

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?")
_YMD_SLASH = re.compile(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?")
_DOTTED = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?")
_SLASH = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*([AaPp][Mm]))?"
)


def parse_datetime(value: str | None) -> datetime | None:
    """Return a naive datetime, or None when the value is not a known shape.

    Slash dates with AM/PM are month/day/year. Slash dates without AM/PM are
    day/month/year when the first number is greater than 12, and month/day/year
    otherwise. Dotted dates are day.month.year, matching Veeam's European
    session reports. No timezone conversion is applied.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    text = re.sub(r"\s+(?:UTC|GMT)$", "", text, flags=re.IGNORECASE)
    if text.endswith("Z"):
        text = text[:-1]

    iso = _ISO.fullmatch(text)
    if iso:
        year, month, day, hour, minute, second = iso.groups()
        return _make(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))

    ymd = _YMD_SLASH.fullmatch(text)
    if ymd:
        year, month, day, hour, minute, second = ymd.groups()
        return _make(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))

    dotted = _DOTTED.fullmatch(text)
    if dotted:
        day, month, year, hour, minute, second = dotted.groups()
        return _make(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))

    slash = _SLASH.fullmatch(text)
    if slash:
        first, second, year, hour, minute, seconds, ampm = slash.groups()
        first_n, second_n = int(first), int(second)
        hour_n = int(hour)
        if ampm:
            if not 1 <= hour_n <= 12:
                return None
            month, day = first_n, second_n
            hour_n = _to_24(hour_n, ampm)
        elif first_n > 12 and second_n <= 12:
            day, month = first_n, second_n
        else:
            month, day = first_n, second_n
        return _make(int(year), month, day, hour_n, int(minute), int(seconds or 0))
    return None


def _to_24(hour: int, ampm: str) -> int:
    base = 0 if hour == 12 else hour
    if ampm.casefold() == "pm":
        return base + 12
    return base


def _make(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
