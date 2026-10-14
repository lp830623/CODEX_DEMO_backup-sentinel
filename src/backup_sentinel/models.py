"""Normalized backup events and the daily digest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class Severity(StrEnum):
    """Urgency shown in the digest, from most urgent to least."""

    CRITICAL = "critical"
    WARNING = "warning"
    OK = "ok"

    @property
    def rank(self) -> int:
        return {Severity.OK: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}[self]


PRODUCT_LABELS: dict[str, str] = {
    "synology.hyper_backup": "Synology Hyper Backup",
    "synology.active_backup": "Synology Active Backup for Business",
    "synology.snapshot": "Synology Snapshot Replication",
    "veeam.backup": "Veeam Backup & Replication",
    "qnap.hbs": "QNAP Hybrid Backup Sync",
}


def fingerprint_for(source: str, job_name: str, target: str) -> str:
    """Stable identity used to recognize the same job across days.

    Matching is case-insensitive and ignores repeated whitespace so a vendor
    that changes capitalization does not look like a new job.
    """

    def norm(value: str) -> str:
        return " ".join(value.casefold().split())

    return "|".join((source, norm(job_name), norm(target)))


@dataclass(frozen=True, slots=True)
class BackupEvent:
    """One backup job, or one object inside a multi-object job, on one day."""

    source: str
    job_name: str
    target: str
    severity: Severity
    raw_status: str
    message: str
    started_at: datetime | None
    finished_at: datetime | None
    observed_on: date
    bytes_transferred: int | None = None
    error_code: str | None = None
    source_path: str | None = None

    @property
    def product(self) -> str:
        return PRODUCT_LABELS.get(self.source, self.source)

    @property
    def fingerprint(self) -> str:
        return fingerprint_for(self.source, self.job_name, self.target)


@dataclass(frozen=True, slots=True)
class DigestItem:
    """A today's event plus repeat-failure context.

    ``severity`` is the digest severity. It matches ``event.severity`` unless a
    chronic warning was escalated to critical. ``event.severity`` stays the
    value parsed from the vendor report.
    """

    event: BackupEvent
    severity: Severity
    streak_days: int
    failures_in_window: int
    chronic: bool
    escalated: bool


@dataclass(frozen=True, slots=True)
class Summary:
    critical: int
    warning: int
    ok: int


@dataclass(frozen=True, slots=True)
class Digest:
    observed_on: date
    generated_at: datetime
    lookback_days: int
    chronic_after_days: int
    items: tuple[DigestItem, ...]

    @property
    def summary(self) -> Summary:
        counts = {level: 0 for level in Severity}
        for item in self.items:
            counts[item.severity] += 1
        return Summary(
            critical=counts[Severity.CRITICAL],
            warning=counts[Severity.WARNING],
            ok=counts[Severity.OK],
        )

    @property
    def chronic_count(self) -> int:
        return sum(1 for item in self.items if item.chronic)
