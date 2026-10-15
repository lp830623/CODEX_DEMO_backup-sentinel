"""Parsers for Synology Hyper Backup, Active Backup, and Snapshot Replication."""

from __future__ import annotations

from datetime import date

from backup_sentinel.models import BackupEvent
from backup_sentinel.parsers.common import parse_labeled_report


class HyperBackupParser:
    source = "synology.hyper_backup"
    signature = "Hyper Backup"

    def detect(self, text: str) -> bool:
        return "hyper backup" in text.casefold()

    def parse(
        self,
        text: str,
        *,
        source_path: str | None,
        fallback_date: date,
    ) -> list[BackupEvent]:
        return parse_labeled_report(
            text,
            source=self.source,
            job_keys=("task", "backup task", "task name"),
            target_keys=("backup destination", "destination"),
            source_path=source_path,
            fallback_date=fallback_date,
            prose_job=True,
            prose_status=True,
        )


class ActiveBackupParser:
    source = "synology.active_backup"
    signature = "Active Backup for Business"

    def detect(self, text: str) -> bool:
        return "active backup for business" in text.casefold()

    def parse(
        self,
        text: str,
        *,
        source_path: str | None,
        fallback_date: date,
    ) -> list[BackupEvent]:
        return parse_labeled_report(
            text,
            source=self.source,
            job_keys=("task", "task name", "backup task"),
            target_keys=("device", "device name", "server"),
            source_path=source_path,
            fallback_date=fallback_date,
        )


class SnapshotReplicationParser:
    source = "synology.snapshot"
    signature = "Snapshot Replication"

    def detect(self, text: str) -> bool:
        return "snapshot replication" in text.casefold()

    def parse(
        self,
        text: str,
        *,
        source_path: str | None,
        fallback_date: date,
    ) -> list[BackupEvent]:
        return parse_labeled_report(
            text,
            source=self.source,
            job_keys=("replication task", "task", "task name"),
            target_keys=("destination",),
            source_path=source_path,
            fallback_date=fallback_date,
        )
