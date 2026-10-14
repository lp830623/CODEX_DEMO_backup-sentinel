"""Parser for QNAP Hybrid Backup Sync (HBS 3) job notifications."""

from __future__ import annotations

from datetime import date

from backup_sentinel.models import BackupEvent
from backup_sentinel.parsers.common import parse_labeled_report


class QnapHbsParser:
    source = "qnap.hbs"
    signature = "Hybrid Backup Sync or HBS 3"

    def detect(self, text: str) -> bool:
        folded = text.casefold()
        return "hybrid backup sync" in folded or "hbs 3" in folded or "hbs3" in folded

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
            job_keys=("job name", "job", "task name", "task"),
            target_keys=("remote destination", "destination", "target"),
            source_path=source_path,
            fallback_date=fallback_date,
        )
