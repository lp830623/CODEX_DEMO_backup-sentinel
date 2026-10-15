"""Detect a backup report and normalize it into events."""

from __future__ import annotations

from datetime import date

from backup_sentinel.errors import ParseError, UnrecognizedReportError
from backup_sentinel.models import BackupEvent
from backup_sentinel.parsers.qnap import QnapHbsParser
from backup_sentinel.parsers.synology import (
    ActiveBackupParser,
    HyperBackupParser,
    SnapshotReplicationParser,
)
from backup_sentinel.parsers.veeam import VeeamParser

PARSERS = (
    HyperBackupParser(),
    ActiveBackupParser(),
    SnapshotReplicationParser(),
    VeeamParser(),
    QnapHbsParser(),
)


def parse_report(
    text: str,
    *,
    fallback_date: date,
    source_path: str | None = None,
) -> list[BackupEvent]:
    """Parse one report. The first matching vendor parser wins."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    where = source_path or "report"
    for parser in PARSERS:
        if not parser.detect(normalized):
            continue
        try:
            events = parser.parse(
                normalized,
                source_path=source_path,
                fallback_date=fallback_date,
            )
        except ParseError as exc:
            raise ParseError(f"{where}: {exc}") from exc
        if not events:
            raise ParseError(f"{where}: no backup jobs found")
        return events
    raise UnrecognizedReportError(f"unrecognized backup report: {where}")
