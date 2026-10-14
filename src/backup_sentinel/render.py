"""Render a digest as plain text, HTML mail, or webhook JSON."""

from __future__ import annotations

import json
from datetime import datetime
from html import escape

from backup_sentinel import __version__
from backup_sentinel.errors import BackupSentinelError
from backup_sentinel.models import BackupEvent, Digest, DigestItem, Severity

SCHEMA_VERSION = 1

_SECTION_COLOR = {
    Severity.CRITICAL: "#9f1239",
    Severity.WARNING: "#92400e",
    Severity.OK: "#166534",
}


def render_text(digest: Digest) -> str:
    summary = digest.summary
    lines = [
        f"Backup Sentinel daily digest — {digest.observed_on.isoformat()}",
        f"Generated: {_generated(digest)}",
        (
            f"Lookback: {digest.lookback_days} days · "
            f"chronic after {digest.chronic_after_days} consecutive non-ok days"
        ),
        "",
        f"Summary: {summary.critical} critical · {summary.warning} warning · {summary.ok} ok",
        "",
    ]
    if not digest.items:
        lines.append("No backup reports for this date.")
        return _finish(lines)

    for severity in (Severity.CRITICAL, Severity.WARNING, Severity.OK):
        group = [item for item in digest.items if item.severity == severity]
        if not group:
            continue
        lines.append(f"{severity.value.upper()} ({len(group)})")
        for item in group:
            lines.append(_heading(item))
            lines.append(_detail(item, digest.lookback_days))
            if severity != Severity.OK:
                message = human_message(item.event)
                if message:
                    lines.append(f"    {message}")
        lines.append("")
    return _finish(lines)


def render_html(digest: Digest) -> str:
    summary = digest.summary
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        '<head><meta charset="utf-8"></head>',
        (
            '<body style="margin:0;padding:24px;background:#f8fafc;'
            'font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#1f2933;">'
        ),
        (
            '<div style="max-width:720px;margin:0 auto;background:#ffffff;'
            'border:1px solid #e5e7eb;border-radius:12px;padding:24px;">'
        ),
        (
            f'<h1 style="margin:0 0 8px;font-size:22px;">Backup Sentinel daily digest'
            f" — {escape(digest.observed_on.isoformat())}</h1>"
        ),
        (f'<p style="margin:0 0 4px;color:#52606d;">Generated {escape(_generated(digest))}</p>'),
        (
            '<p style="margin:0 0 16px;color:#52606d;">'
            f"Lookback {digest.lookback_days} days · chronic after "
            f"{digest.chronic_after_days} consecutive non-ok days</p>"
        ),
        (
            '<p style="margin:0 0 20px;font-size:16px;">'
            f"<strong>{summary.critical}</strong> critical · "
            f"<strong>{summary.warning}</strong> warning · "
            f"<strong>{summary.ok}</strong> ok</p>"
        ),
    ]
    if not digest.items:
        parts.append("<p>No backup reports for this date.</p>")
    for severity in (Severity.CRITICAL, Severity.WARNING, Severity.OK):
        group = [item for item in digest.items if item.severity == severity]
        if not group:
            continue
        color = _SECTION_COLOR[severity]
        parts.append(
            f'<h2 style="margin:20px 0 8px;font-size:16px;color:{color};">'
            f"{escape(severity.value.upper())} ({len(group)})</h2>"
        )
        parts.append('<table style="width:100%;border-collapse:collapse;">')
        for item in group:
            message = human_message(item.event) if severity != Severity.OK else ""
            detail = _detail(item, digest.lookback_days).strip()
            parts.append(
                "<tr>"
                '<td style="padding:8px 0;border-top:1px solid #e5e7eb;vertical-align:top;">'
                f'<div style="font-weight:600;">{escape(_heading(item).strip())}</div>'
                f'<div style="color:#52606d;margin-top:2px;">{escape(detail)}</div>'
                + (f'<div style="margin-top:2px;">{escape(message)}</div>' if message else "")
                + "</td></tr>"
            )
        parts.append("</table>")
    parts.append(
        '<p style="margin:24px 0 0;color:#7b8794;font-size:12px;">'
        f"backup-sentinel {escape(__version__)}</p>"
    )
    parts.extend(["</div>", "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def render_json(digest: Digest) -> str:
    return json.dumps(digest_payload(digest), indent=2, ensure_ascii=False) + "\n"


def render_subject(template: str, digest: Digest) -> str:
    summary = digest.summary
    try:
        subject = template.format(
            date=digest.observed_on.isoformat(),
            critical=summary.critical,
            warning=summary.warning,
            ok=summary.ok,
            chronic=digest.chronic_count,
        )
    except KeyError as exc:
        raise BackupSentinelError(f"email subject placeholder {exc} is unknown") from exc
    return " ".join(subject.split())


def digest_payload(digest: Digest) -> dict[str, object]:
    summary = digest.summary
    return {
        "tool": "backup-sentinel",
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "date": digest.observed_on.isoformat(),
        "generated_at": digest.generated_at.isoformat(timespec="seconds"),
        "lookback_days": digest.lookback_days,
        "chronic_after_days": digest.chronic_after_days,
        "summary": {
            "critical": summary.critical,
            "warning": summary.warning,
            "ok": summary.ok,
            "chronic": digest.chronic_count,
        },
        "items": [
            {
                "severity": item.severity.value,
                "streak_days": item.streak_days,
                "failures_in_window": item.failures_in_window,
                "chronic": item.chronic,
                "escalated": item.escalated,
                "event": event_payload(item.event),
            }
            for item in digest.items
        ],
    }


def event_payload(event: BackupEvent) -> dict[str, object]:
    return {
        "source": event.source,
        "product": event.product,
        "job_name": event.job_name,
        "target": event.target,
        "fingerprint": event.fingerprint,
        "severity": event.severity.value,
        "raw_status": event.raw_status,
        "message": event.message,
        "error_code": event.error_code,
        "bytes_transferred": event.bytes_transferred,
        "started_at": _iso(event.started_at),
        "finished_at": _iso(event.finished_at),
        "observed_on": event.observed_on.isoformat(),
        "source_path": event.source_path,
    }


def human_message(event: BackupEvent) -> str:
    message = event.message.strip()
    code = (event.error_code or "").strip()
    if code and code not in message:
        suffix = f"(error {code})"
        message = f"{message} {suffix}".strip()
    return message


def _heading(item: DigestItem) -> str:
    target = f" → {item.event.target}" if item.event.target else ""
    return f"  {item.event.product} · {item.event.job_name}{target}"


def _detail(item: DigestItem, lookback_days: int) -> str:
    parts = [item.event.raw_status]
    if item.streak_days:
        parts.append(f"{item.streak_days}-day streak")
    if item.failures_in_window:
        noun = "failure" if item.failures_in_window == 1 else "failures"
        parts.append(f"{item.failures_in_window} {noun} in {lookback_days} days")
    if item.chronic:
        parts.append("chronic")
    if item.escalated:
        parts.append("escalated")
    return "    " + " · ".join(parts)


def _generated(digest: Digest) -> str:
    return digest.generated_at.strftime("%Y-%m-%d %H:%M %Z").strip()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"
