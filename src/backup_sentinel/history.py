"""SQLite history of one observation per job per calendar day.

Escalation is not stored. The digest recomputes streaks from the vendor
severity, so changing ``chronic_after_days`` does not require a reload.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from backup_sentinel.models import BackupEvent, Severity

_COLUMNS = (
    "fingerprint",
    "observed_on",
    "source",
    "job_name",
    "target",
    "severity",
    "raw_status",
    "message",
    "error_code",
    "bytes_transferred",
    "started_at",
    "finished_at",
    "source_path",
    "recorded_at",
)


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def upsert(self, events: Sequence[BackupEvent]) -> None:
        if not events:
            return
        recorded = datetime.now(UTC).isoformat(timespec="seconds")
        rows = [_row(event, recorded) for event in events]
        placeholders = ", ".join("?" for _ in _COLUMNS)
        assignments = ", ".join(
            f"{column}=excluded.{column}"
            for column in _COLUMNS
            if column not in {"fingerprint", "observed_on"}
        )
        sql = (
            f"INSERT INTO observations ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(fingerprint, observed_on) DO UPDATE SET {assignments}"
        )
        conn = self._connect()
        try:
            conn.executemany(sql, rows)
            conn.commit()
        finally:
            conn.close()

    def load_between(self, start: date, end: date) -> list[BackupEvent]:
        if not self.path.exists():
            return []
        sql = (
            f"SELECT {', '.join(_COLUMNS)} FROM observations "
            "WHERE observed_on >= ? AND observed_on <= ? ORDER BY observed_on"
        )
        conn = self._connect()
        try:
            found = conn.execute(sql, (start.isoformat(), end.isoformat())).fetchall()
        finally:
            conn.close()
        return [_event(row) for row in found]

    def latest_date(self) -> date | None:
        if not self.path.exists():
            return None
        conn = self._connect()
        try:
            row = conn.execute("SELECT MAX(observed_on) FROM observations").fetchone()
        finally:
            conn.close()
        if row is None or row[0] is None:
            return None
        return date.fromisoformat(row[0])

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                fingerprint TEXT NOT NULL,
                observed_on TEXT NOT NULL,
                source TEXT NOT NULL,
                job_name TEXT NOT NULL,
                target TEXT NOT NULL,
                severity TEXT NOT NULL,
                raw_status TEXT NOT NULL,
                message TEXT NOT NULL,
                error_code TEXT,
                bytes_transferred INTEGER,
                started_at TEXT,
                finished_at TEXT,
                source_path TEXT,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (fingerprint, observed_on)
            )
            """
        )
        return conn


def _row(event: BackupEvent, recorded_at: str) -> tuple[object, ...]:
    return (
        event.fingerprint,
        event.observed_on.isoformat(),
        event.source,
        event.job_name,
        event.target,
        event.severity.value,
        event.raw_status,
        event.message,
        event.error_code,
        event.bytes_transferred,
        _stamp(event.started_at),
        _stamp(event.finished_at),
        event.source_path,
        recorded_at,
    )


def _event(row: sqlite3.Row) -> BackupEvent:
    return BackupEvent(
        source=row["source"],
        job_name=row["job_name"],
        target=row["target"],
        severity=Severity(row["severity"]),
        raw_status=row["raw_status"],
        message=row["message"],
        started_at=_parse_stamp(row["started_at"]),
        finished_at=_parse_stamp(row["finished_at"]),
        observed_on=date.fromisoformat(row["observed_on"]),
        bytes_transferred=row["bytes_transferred"],
        error_code=row["error_code"],
        source_path=row["source_path"],
    )


def _stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def _parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
