"""Rank today's reports and attach repeat-failure context."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from backup_sentinel.models import BackupEvent, Digest, DigestItem, Severity


def streak_days(severities: dict[date, Severity], end: date) -> int:
    """Count consecutive non-ok days ending at ``end``.

    A missing calendar day ends the streak. Callers load only the lookback
    window, so a streak cannot grow longer than that window.
    """
    count = 0
    day = end
    while True:
        severity = severities.get(day)
        if severity is None or severity == Severity.OK:
            return count
        count += 1
        day -= timedelta(days=1)


def build_digest(
    observations: Sequence[BackupEvent],
    *,
    observed_on: date,
    lookback_days: int,
    chronic_after_days: int,
    escalate_chronic_warnings: bool,
    generated_at: datetime,
) -> Digest:
    """Build the digest for ``observed_on`` from events inside the window.

    Jobs with no report on ``observed_on`` are omitted. A quiet day is not
    treated as a success or a failure.
    """
    window_start = observed_on - timedelta(days=lookback_days - 1)
    by_fingerprint: dict[str, dict[date, BackupEvent]] = {}
    for event in observations:
        if event.observed_on < window_start or event.observed_on > observed_on:
            continue
        series = by_fingerprint.setdefault(event.fingerprint, {})
        current = series.get(event.observed_on)
        if current is None or _later(event, current):
            series[event.observed_on] = event

    items: list[DigestItem] = []
    for series in by_fingerprint.values():
        today = series.get(observed_on)
        if today is None:
            continue
        severities = {day: event.severity for day, event in series.items()}
        streak = streak_days(severities, observed_on)
        failures = sum(1 for severity in severities.values() if severity != Severity.OK)
        chronic = streak >= chronic_after_days and today.severity != Severity.OK
        severity = today.severity
        escalated = False
        if escalate_chronic_warnings and chronic and today.severity == Severity.WARNING:
            severity = Severity.CRITICAL
            escalated = True
        items.append(
            DigestItem(
                event=today,
                severity=severity,
                streak_days=streak,
                failures_in_window=failures,
                chronic=chronic,
                escalated=escalated,
            )
        )

    items.sort(
        key=lambda item: (
            -item.severity.rank,
            not item.chronic,
            -item.streak_days,
            -item.failures_in_window,
            item.event.source,
            item.event.job_name.casefold(),
            item.event.target.casefold(),
        )
    )
    return Digest(
        observed_on=observed_on,
        generated_at=generated_at,
        lookback_days=lookback_days,
        chronic_after_days=chronic_after_days,
        items=tuple(items),
    )


def _later(candidate: BackupEvent, current: BackupEvent) -> bool:
    candidate_stamp = candidate.finished_at or candidate.started_at
    current_stamp = current.finished_at or current.started_at
    if candidate_stamp is None:
        return False
    if current_stamp is None:
        return True
    return candidate_stamp >= current_stamp
