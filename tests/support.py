"""Builders shared by digest and render tests."""

from datetime import date, datetime

from backup_sentinel.models import BackupEvent, Severity

_UNSET = object()


def event(
    *,
    source: str = "synology.hyper_backup",
    job_name: str = "Documents-Daily",
    target: str = "vault-lab.example.internal",
    severity: Severity = Severity.CRITICAL,
    raw_status: str = "Failed",
    message: str = "The backup destination is offline.",
    started_at: datetime | None | object = _UNSET,
    finished_at: datetime | None | object = _UNSET,
    observed_on: date | object = _UNSET,
    bytes_transferred: int | None = 0,
    error_code: str | None = "31",
    source_path: str | None = None,
) -> BackupEvent:
    resolved_start = datetime(2026, 10, 14, 2, 0, 11) if started_at is _UNSET else started_at
    resolved_finish = datetime(2026, 10, 14, 2, 1, 6) if finished_at is _UNSET else finished_at
    resolved_day = date(2026, 10, 14) if observed_on is _UNSET else observed_on
    assert isinstance(resolved_start, datetime) or resolved_start is None
    assert isinstance(resolved_finish, datetime) or resolved_finish is None
    assert isinstance(resolved_day, date)
    return BackupEvent(
        source=source,
        job_name=job_name,
        target=target,
        severity=severity,
        raw_status=raw_status,
        message=message,
        started_at=resolved_start,
        finished_at=resolved_finish,
        observed_on=resolved_day,
        bytes_transferred=bytes_transferred,
        error_code=error_code,
        source_path=source_path,
    )
