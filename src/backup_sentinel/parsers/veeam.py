"""Parser for Veeam Backup & Replication session reports.

Object rows are the source of truth when a report lists them. Every object
shares the session start and end, because the plain-text and summary HTML
layouts used here do not carry per-object timestamps.
"""

from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser

from backup_sentinel.dates import parse_datetime
from backup_sentinel.errors import ParseError
from backup_sentinel.models import BackupEvent
from backup_sentinel.parsers.common import extract_fields, lookup, make_event, parse_size

_OBJECT_RE = re.compile(
    r"^(?P<name>[^|\n]+?)\s*\|\s*"
    r"(?P<status>Success(?:ful)?|Warning|Failed|Error)\s*\|\s*"
    r"(?P<size>[^|\n]+?)"
    r"(?:\s*\|\s*(?P<details>[^|\n]*))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_HEADER_ALIASES = {
    "name": ("name", "object", "vm", "machine", "job object"),
    "status": ("status", "result", "state"),
    "size": ("size", "transferred", "data size"),
    "details": ("details", "message", "error", "description"),
}


class VeeamParser:
    source = "veeam.backup"
    signature = "Veeam Backup"

    def detect(self, text: str) -> bool:
        return "veeam backup" in text.casefold()

    def parse(
        self,
        text: str,
        *,
        source_path: str | None,
        fallback_date: date,
    ) -> list[BackupEvent]:
        if _looks_like_html(text):
            events = _parse_html(text, source_path=source_path, fallback_date=fallback_date)
            if events:
                return events
            text = _visible_text(text)
        return _parse_text(text, source_path=source_path, fallback_date=fallback_date)


def _parse_text(
    text: str,
    *,
    source_path: str | None,
    fallback_date: date,
) -> list[BackupEvent]:
    found = extract_fields(text)
    job = lookup(found, "job", "job name", "backup job")
    if not job:
        raise ParseError("missing job name")
    started = parse_datetime(lookup(found, "session start", "start time", "started", "start"))
    finished = parse_datetime(lookup(found, "session end", "end time", "finished", "end"))
    objects = list(_OBJECT_RE.finditer(text))
    if objects:
        events: list[BackupEvent] = []
        for match in objects:
            details = (match.group("details") or "").strip()
            events.append(
                make_event(
                    source=VeeamParser.source,
                    job_name=job,
                    target=match.group("name").strip(),
                    raw_status=match.group("status").strip(),
                    message="" if details.casefold() == "processed" else details,
                    started_at=started,
                    finished_at=finished,
                    fallback_date=fallback_date,
                    bytes_transferred=parse_size(match.group("size")),
                    source_path=source_path,
                )
            )
        return events

    raw_status = lookup(found, "result", "status")
    if not raw_status:
        raise ParseError("missing result")
    message = lookup(found, "error", "error message", "message", "details") or ""
    return [
        make_event(
            source=VeeamParser.source,
            job_name=job,
            target="",
            raw_status=raw_status,
            message=message,
            started_at=started,
            finished_at=finished,
            fallback_date=fallback_date,
            bytes_transferred=parse_size(lookup(found, "transferred size", "transferred", "size")),
            error_code=lookup(found, "error code"),
            source_path=source_path,
        )
    ]


def _parse_html(
    text: str,
    *,
    source_path: str | None,
    fallback_date: date,
) -> list[BackupEvent]:
    collector = _HtmlBits()
    collector.feed(text)
    collector.close()
    prose = "\n".join([*collector.headings, *collector.paragraphs])
    found = extract_fields(prose)
    job = lookup(found, "job", "job name", "backup job")
    if job is None:
        for heading in collector.headings:
            if "veeam backup" not in heading.casefold() and heading.strip():
                job = heading.strip()
                break
    rows = _object_rows(collector.tables)
    if not job or not rows:
        return []
    started = parse_datetime(lookup(found, "session start", "start time", "started", "start"))
    finished = parse_datetime(lookup(found, "session end", "end time", "finished", "end"))
    events: list[BackupEvent] = []
    for name, status, size, details in rows:
        events.append(
            make_event(
                source=VeeamParser.source,
                job_name=job,
                target=name,
                raw_status=status,
                message="" if details.casefold() == "processed" else details,
                started_at=started,
                finished_at=finished,
                fallback_date=fallback_date,
                bytes_transferred=parse_size(size),
                source_path=source_path,
            )
        )
    return events


def _object_rows(tables: list[list[list[str]]]) -> list[tuple[str, str, str, str]]:
    for table in tables:
        if not table:
            continue
        columns = _column_index(table[0])
        if "name" not in columns or "status" not in columns:
            continue
        rows: list[tuple[str, str, str, str]] = []
        for raw in table[1:]:
            name = _cell(raw, columns.get("name"))
            status = _cell(raw, columns.get("status"))
            if not name or not status:
                continue
            if name.casefold() in _HEADER_ALIASES["name"]:
                continue
            rows.append(
                (
                    name,
                    status,
                    _cell(raw, columns.get("size")),
                    _cell(raw, columns.get("details")),
                )
            )
        if rows:
            return rows
    return []


def _column_index(header: list[str]) -> dict[str, int]:
    folded = [cell.casefold() for cell in header]
    mapping: dict[str, int] = {}
    for key, names in _HEADER_ALIASES.items():
        for index, cell in enumerate(folded):
            if cell in names:
                mapping[key] = index
                break
    return mapping


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _looks_like_html(text: str) -> bool:
    folded = text.casefold()
    return "<html" in folded or "<table" in folded


def _visible_text(text: str) -> str:
    return _TAG_RE.sub(" ", text)


class _HtmlBits(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.paragraphs: list[str] = []
        self.headings: list[str] = []
        self._table_depth = 0
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self._table: list[list[str]] = []
        self._capture: list[str] | None = None
        self._bucket: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table = []
        elif tag == "tr" and self._table_depth:
            self._row = []
        elif tag in {"td", "th"} and self._table_depth:
            self._in_cell = True
            self._cell = []
        elif tag == "p":
            self._capture = []
            self._bucket = self.paragraphs
        elif tag in {"h1", "h2", "h3", "title"}:
            self._capture = []
            self._bucket = self.headings
        elif tag == "br" and self._in_cell:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(" ".join("".join(self._cell).split()))
            self._in_cell = False
        elif tag == "tr" and self._table_depth and any(self._row):
            self._table.append(self._row)
            self._row = []
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self.tables.append(self._table)
                self._table = []
        elif tag == "p" and self._bucket is self.paragraphs:
            self._flush_capture()
        elif tag in {"h1", "h2", "h3", "title"} and self._bucket is self.headings:
            self._flush_capture()

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)
        if self._capture is not None:
            self._capture.append(data)

    def _flush_capture(self) -> None:
        if self._capture is not None and self._bucket is not None:
            text = " ".join("".join(self._capture).split())
            if text:
                self._bucket.append(text)
        self._capture = None
        self._bucket = None
