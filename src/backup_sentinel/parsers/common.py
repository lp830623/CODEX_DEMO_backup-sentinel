"""Shared field, size, and event helpers for vendor parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

from backup_sentinel.dates import parse_datetime
from backup_sentinel.errors import ParseError
from backup_sentinel.models import BackupEvent, Severity
from backup_sentinel.status import classify_status

_FIELD_RE = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z0-9 /()_-]{0,48}?)\s*:\s*(?P<value>\S.*?)\s*$",
    re.MULTILINE,
)
_BRACKET_JOB = re.compile(r"(?i)\b(?:backup task|replication task|task|job)\s+\[(?P<name>[^\]]+)\]")
_PROSE_FAILED = re.compile(r"\bfailed\b|\bfailure\b", re.IGNORECASE)
_PROSE_WARNING = re.compile(r"\bwarning", re.IGNORECASE)
_PROSE_OK = re.compile(r"\bsuccess", re.IGNORECASE)
_CODE_RE = re.compile(r"(?i)\b(?:error\s*code|code)\s*[:=]\s*([A-Za-z0-9_-]+)")
_SIZE_RE = re.compile(
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>bytes|byte|KiB|MiB|GiB|TiB|KB|MB|GB|TB|B)\b",
    re.IGNORECASE,
)
_SIZE_UNITS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}

_START_KEYS = ("start time", "session start", "started", "start")
_END_KEYS = ("end time", "session end", "finished", "finish time", "end")
_SIZE_KEYS = ("transferred size", "data transferred", "data size", "transferred", "size")
_MESSAGE_LIMIT = 500


def extract_fields(text: str) -> dict[str, str]:
    """Read ``Label: value`` lines. The first occurrence of a label wins."""
    found: dict[str, str] = {}
    for match in _FIELD_RE.finditer(text):
        key = " ".join(match.group("label").split()).casefold()
        found.setdefault(key, match.group("value").strip())
    return found


def lookup(found: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = found.get(key)
        if value:
            return value
    return None


def parse_size(value: str | None) -> int | None:
    """Parse a size using 1024-based KB/MB/GB/TB units.

    ``12.4 GB`` is ``int(12.4 * 1024**3)``. Thousands separators in the number
    are ignored. Returns None when no size is present.
    """
    if value is None:
        return None
    match = _SIZE_RE.search(value)
    if not match:
        return None
    number = float(match.group("number").replace(",", ""))
    unit = match.group("unit").casefold()
    return int(number * _SIZE_UNITS[unit])


def clip_message(value: str) -> str:
    text = " ".join(value.split())
    if len(text) <= _MESSAGE_LIMIT:
        return text
    return text[: _MESSAGE_LIMIT - 3].rstrip() + "..."


def make_event(
    *,
    source: str,
    job_name: str,
    target: str,
    raw_status: str,
    message: str,
    started_at: datetime | None,
    finished_at: datetime | None,
    fallback_date: date,
    bytes_transferred: int | None = None,
    error_code: str | None = None,
    source_path: str | None = None,
) -> BackupEvent:
    job = " ".join(job_name.split())
    if not job:
        raise ParseError("missing job name")
    status = " ".join(raw_status.split())
    if not status:
        raise ParseError("missing status")
    stamp = finished_at or started_at
    observed = stamp.date() if stamp is not None else fallback_date
    code = " ".join((error_code or "").split()) or None
    return BackupEvent(
        source=source,
        job_name=job,
        target=" ".join(target.split()),
        severity=classify_status(status),
        raw_status=status,
        message=clip_message(message),
        started_at=started_at,
        finished_at=finished_at,
        observed_on=observed,
        bytes_transferred=bytes_transferred,
        error_code=code,
        source_path=source_path,
    )


def parse_labeled_report(
    text: str,
    *,
    source: str,
    job_keys: tuple[str, ...],
    target_keys: tuple[str, ...],
    source_path: str | None,
    fallback_date: date,
    prose_job: bool = False,
    prose_status: bool = False,
) -> list[BackupEvent]:
    """Parse a single-job report laid out as ``Label: value`` lines."""
    found = extract_fields(text)
    job = lookup(found, *job_keys)
    if job is None and prose_job:
        job = _bracket_job(text)
    if job is None:
        raise ParseError("missing job name")

    raw_status = lookup(found, "status", "result")
    if raw_status is None and prose_status:
        raw_status = _prose_status(text)
    if raw_status is None:
        raise ParseError("missing status")

    severity = classify_status(raw_status)
    message = _message_for(found, severity)
    error_code = lookup(found, "error code") or _inline_code(text)
    started = parse_datetime(lookup(found, *_START_KEYS))
    finished = parse_datetime(lookup(found, *_END_KEYS))
    target = lookup(found, *target_keys) or ""
    return [
        make_event(
            source=source,
            job_name=job,
            target=target,
            raw_status=raw_status,
            message=message,
            started_at=started,
            finished_at=finished,
            fallback_date=fallback_date,
            bytes_transferred=parse_size(lookup(found, *_SIZE_KEYS)),
            error_code=error_code,
            source_path=source_path,
        )
    ]


def _message_for(found: dict[str, str], severity: Severity) -> str:
    error = lookup(found, "error", "error message")
    warning = lookup(found, "warning", "details")
    message = lookup(found, "message")
    if severity == Severity.CRITICAL:
        return error or warning or message or ""
    if severity == Severity.WARNING:
        return warning or error or message or ""
    return message or ""


def _bracket_job(text: str) -> str | None:
    match = _BRACKET_JOB.search(text)
    if not match:
        return None
    return match.group("name").strip() or None


def _prose_status(text: str) -> str | None:
    head = "\n".join(text.splitlines()[:12])
    if _PROSE_FAILED.search(head):
        return "Failed"
    if _PROSE_WARNING.search(head):
        return "Warning"
    if _PROSE_OK.search(head):
        return "Successful"
    return None


def _inline_code(text: str) -> str | None:
    match = _CODE_RE.search(text)
    if not match:
        return None
    return match.group(1)
