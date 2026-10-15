import json
import textwrap
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from backup_sentinel.errors import BackupSentinelError
from backup_sentinel.models import Digest, DigestItem, Severity
from backup_sentinel.render import (
    digest_payload,
    render_html,
    render_json,
    render_subject,
    render_text,
)
from tests.support import event


def _sample_digest() -> Digest:
    critical = DigestItem(
        event=event(),
        severity=Severity.CRITICAL,
        streak_days=3,
        failures_in_window=3,
        chronic=True,
        escalated=False,
    )
    recovered = DigestItem(
        event=event(
            source="qnap.hbs",
            job_name="Offsite-Photos",
            target="vault-lab.example.internal:/share/photos",
            severity=Severity.OK,
            raw_status="Completed",
            message="Sync finished.",
            error_code=None,
            bytes_transferred=int(8.6 * 1024**3),
        ),
        severity=Severity.OK,
        streak_days=0,
        failures_in_window=1,
        chronic=False,
        escalated=False,
    )
    return Digest(
        observed_on=date(2026, 10, 14),
        generated_at=datetime(2026, 10, 14, 7, 15, tzinfo=ZoneInfo("UTC")),
        lookback_days=7,
        chronic_after_days=3,
        items=(critical, recovered),
    )


def test_text_digest_layout() -> None:
    expected = textwrap.dedent(
        """\
        Backup Sentinel daily digest — 2026-10-14
        Generated: 2026-10-14 07:15 UTC
        Lookback: 7 days · chronic after 3 consecutive non-ok days

        Summary: 1 critical · 0 warning · 1 ok

        CRITICAL (1)
          Synology Hyper Backup · Documents-Daily → vault-lab.example.internal
            Failed · 3-day streak · 3 failures in 7 days · chronic
            The backup destination is offline. (error 31)

        OK (1)
          QNAP Hybrid Backup Sync · Offsite-Photos → vault-lab.example.internal:/share/photos
            Completed · 1 failure in 7 days
        """
    )
    assert render_text(_sample_digest()) == expected


def test_empty_digest_does_not_claim_success() -> None:
    digest = Digest(
        observed_on=date(2026, 10, 14),
        generated_at=datetime(2026, 10, 14, 7, 15, tzinfo=ZoneInfo("UTC")),
        lookback_days=7,
        chronic_after_days=3,
        items=(),
    )
    text = render_text(digest)
    assert "No backup reports for this date." in text
    assert "Summary: 0 critical · 0 warning · 0 ok" in text
    assert "healthy" not in text.casefold()


def test_html_escapes_messages() -> None:
    digest = Digest(
        observed_on=date(2026, 10, 14),
        generated_at=datetime(2026, 10, 14, 7, 15, tzinfo=ZoneInfo("UTC")),
        lookback_days=7,
        chronic_after_days=3,
        items=(
            DigestItem(
                event=event(message="failed <script>"),
                severity=Severity.CRITICAL,
                streak_days=1,
                failures_in_window=1,
                chronic=False,
                escalated=False,
            ),
        ),
    )
    html = render_html(digest)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "CRITICAL (1)" in html


def test_json_schema_keeps_vendor_severity_on_the_event() -> None:
    payload = json.loads(render_json(_sample_digest()))
    assert payload["schema_version"] == 1
    assert payload["tool"] == "backup-sentinel"
    assert payload["summary"] == {"critical": 1, "warning": 0, "ok": 1, "chronic": 1}
    assert payload["items"][0]["severity"] == "critical"
    assert payload["items"][0]["event"]["error_code"] == "31"
    assert payload["items"][0]["event"]["fingerprint"].startswith("synology.hyper_backup|")
    assert digest_payload(_sample_digest())["date"] == "2026-10-14"


def test_subject_placeholders() -> None:
    subject = render_subject(
        "Backup digest {date}: {critical} critical, {warning} warning, {ok} ok",
        _sample_digest(),
    )
    assert subject == "Backup digest 2026-10-14: 1 critical, 0 warning, 1 ok"


def test_unknown_subject_placeholder() -> None:
    with pytest.raises(BackupSentinelError, match="placeholder"):
        render_subject("{missing}", _sample_digest())
