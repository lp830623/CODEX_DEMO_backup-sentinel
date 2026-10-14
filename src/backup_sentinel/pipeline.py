"""Ingest reports, update history, rank a day, and deliver the digest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backup_sentinel.config import AppConfig, InputConfig
from backup_sentinel.delivery import email as email_delivery
from backup_sentinel.delivery import webhook as webhook_delivery
from backup_sentinel.digest import build_digest
from backup_sentinel.errors import BackupSentinelError
from backup_sentinel.history import HistoryStore
from backup_sentinel.inbox import discover_files, parse_files
from backup_sentinel.models import BackupEvent, Digest
from backup_sentinel.render import (
    digest_payload,
    render_html,
    render_json,
    render_subject,
    render_text,
)


@dataclass(frozen=True, slots=True)
class RunResult:
    digest: Digest
    notices: tuple[str, ...]
    deliveries: tuple[str, ...]
    output: str
    exit_code: int


def execute(
    config: AppConfig,
    *,
    command: str,
    digest_date: date | None,
    dry_run: bool,
    fail_on: str,
    output_format: str,
    input_paths: list[Path] | None = None,
    now: datetime | None = None,
) -> RunResult:
    generated_at = now or datetime.now(ZoneInfo(config.timezone))
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=ZoneInfo(config.timezone))
    fallback = digest_date or generated_at.date()
    notices: list[str] = []
    events: list[BackupEvent] = []

    if command == "run":
        inputs = _override_inputs(input_paths) if input_paths else config.inputs
        files = discover_files(inputs)
        events, parse_notices = parse_files(files, fallback_date=fallback)
        notices.extend(parse_notices)
        events = dedupe_events(events)

    store = HistoryStore(config.history.path)
    observed_on = _choose_date(
        command=command,
        requested=digest_date,
        events=events,
        store=store,
        today=generated_at.date(),
    )
    window_start = observed_on - timedelta(days=config.history.lookback_days - 1)
    if command == "report" and not store.path.exists():
        notices.append("history database does not exist yet")

    if command == "run" and not dry_run:
        store.upsert(events)
        observations = store.load_between(window_start, observed_on)
    else:
        stored = store.load_between(window_start, observed_on)
        observations = _merge(stored, events, window_start, observed_on)

    digest = build_digest(
        observations,
        observed_on=observed_on,
        lookback_days=config.history.lookback_days,
        chronic_after_days=config.history.chronic_after_days,
        escalate_chronic_warnings=config.escalate_chronic_warnings,
        generated_at=generated_at,
    )
    if events and not digest.items:
        ingested = ", ".join(sorted({event.observed_on.isoformat() for event in events}))
        notices.append(f"no reports dated {observed_on.isoformat()}; ingested dates: {ingested}")

    output = render_json(digest) if output_format == "json" else render_text(digest)
    ingest_failed = command == "run" and not events
    if ingest_failed:
        notices.append("no recognized backup reports were ingested")
        deliveries = ["delivery: skipped, nothing ingested"]
        failed = True
    else:
        deliveries, failed = _deliver(config, digest, dry_run=dry_run)
    exit_code = 1 if failed else _fail_on(digest, fail_on)
    return RunResult(
        digest=digest,
        notices=tuple(notices),
        deliveries=tuple(deliveries),
        output=output,
        exit_code=exit_code,
    )


def dedupe_events(events: list[BackupEvent]) -> list[BackupEvent]:
    """Keep the latest report for each job on each calendar day."""
    chosen: dict[tuple[str, date], BackupEvent] = {}
    order: list[tuple[str, date]] = []
    for event in events:
        key = (event.fingerprint, event.observed_on)
        current = chosen.get(key)
        if current is None:
            order.append(key)
            chosen[key] = event
        elif _newer(event, current):
            chosen[key] = event
    return [chosen[key] for key in order]


def _override_inputs(paths: list[Path]) -> tuple[InputConfig, ...]:
    items: list[InputConfig] = []
    for path in paths:
        candidate = path if path.is_absolute() else Path.cwd() / path
        items.append(InputConfig(path=candidate.resolve(), recursive=True))
    return tuple(items)


def _choose_date(
    *,
    command: str,
    requested: date | None,
    events: list[BackupEvent],
    store: HistoryStore,
    today: date,
) -> date:
    if requested is not None:
        return requested
    if command == "run" and events:
        return max(event.observed_on for event in events)
    latest = store.latest_date()
    return latest or today


def _merge(
    stored: list[BackupEvent],
    fresh: list[BackupEvent],
    start: date,
    end: date,
) -> list[BackupEvent]:
    merged: dict[tuple[str, date], BackupEvent] = {
        (event.fingerprint, event.observed_on): event for event in stored
    }
    for event in fresh:
        if event.observed_on < start or event.observed_on > end:
            continue
        key = (event.fingerprint, event.observed_on)
        current = merged.get(key)
        if current is None or _newer(event, current):
            merged[key] = event
    return list(merged.values())


def _newer(candidate: BackupEvent, current: BackupEvent) -> bool:
    candidate_stamp = candidate.finished_at or candidate.started_at
    current_stamp = current.finished_at or current.started_at
    if candidate_stamp is None:
        return False
    if current_stamp is None:
        return True
    return candidate_stamp >= current_stamp


def _deliver(config: AppConfig, digest: Digest, *, dry_run: bool) -> tuple[list[str], bool]:
    if dry_run:
        return ["delivery: dry-run, nothing sent"], False
    notes: list[str] = []
    failed = False
    text = render_text(digest)
    html = render_html(digest)
    if config.email.enabled:
        try:
            email_delivery.send_email(
                config.email,
                subject=render_subject(config.email.subject, digest),
                text=text,
                html=html,
            )
            notes.append("delivery: email sent to " + ", ".join(config.email.mail_to))
        except BackupSentinelError as exc:
            notes.append(f"delivery: email failed: {exc}")
            failed = True
    else:
        notes.append("delivery: email disabled")

    if config.webhook.enabled:
        try:
            status = webhook_delivery.post_json(
                config.webhook.url,
                digest_payload(digest),
                dict(config.webhook.headers),
                config.webhook.timeout_seconds,
            )
            notes.append(f"delivery: webhook posted ({status})")
        except BackupSentinelError as exc:
            notes.append(f"delivery: webhook failed: {exc}")
            failed = True
    else:
        notes.append("delivery: webhook disabled")
    return notes, failed


def _fail_on(digest: Digest, fail_on: str) -> int:
    summary = digest.summary
    if fail_on == "critical" and summary.critical:
        return 2
    if fail_on == "warning" and (summary.critical or summary.warning):
        return 2
    return 0
