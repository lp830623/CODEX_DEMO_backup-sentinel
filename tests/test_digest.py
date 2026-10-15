from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backup_sentinel.digest import build_digest, streak_days
from backup_sentinel.models import Severity, fingerprint_for
from tests.support import event

GENERATED = datetime(2026, 10, 14, 7, 15, tzinfo=ZoneInfo("UTC"))


def _digest(events, *, observed_on=date(2026, 10, 14), lookback=7, chronic=3, escalate=True):
    return build_digest(
        events,
        observed_on=observed_on,
        lookback_days=lookback,
        chronic_after_days=chronic,
        escalate_chronic_warnings=escalate,
        generated_at=GENERATED,
    )


def test_fingerprint_ignores_case_and_spacing() -> None:
    left = fingerprint_for("veeam.backup", "Nightly-VM-Backup", "VM-DB-01")
    right = fingerprint_for("veeam.backup", "  nightly-vm-backup ", "vm-db-01")
    assert left == right


def test_missing_day_breaks_the_streak() -> None:
    events = [
        event(observed_on=date(2026, 10, 12), finished_at=datetime(2026, 10, 12, 2, 1)),
        event(observed_on=date(2026, 10, 14), finished_at=datetime(2026, 10, 14, 2, 1)),
    ]
    item = _digest(events).items[0]
    assert item.streak_days == 1
    assert item.failures_in_window == 2
    assert item.chronic is False


def test_failures_outside_the_window_are_ignored() -> None:
    events = [
        event(observed_on=date(2026, 10, 1), finished_at=datetime(2026, 10, 1, 2, 1)),
        event(observed_on=date(2026, 10, 14), finished_at=datetime(2026, 10, 14, 2, 1)),
    ]
    item = _digest(events, lookback=7).items[0]
    assert item.streak_days == 1
    assert item.failures_in_window == 1


def test_streak_helper_stops_on_success() -> None:
    severities = {
        date(2026, 10, 12): Severity.CRITICAL,
        date(2026, 10, 13): Severity.OK,
        date(2026, 10, 14): Severity.CRITICAL,
    }
    assert streak_days(severities, date(2026, 10, 14)) == 1


def test_chronic_warning_escalates() -> None:
    events = []
    for offset in range(3):
        day = date(2026, 10, 12) + timedelta(days=offset)
        events.append(
            event(
                source="synology.active_backup",
                job_name="Fileserver-Lab",
                target="fileserver-lab",
                severity=Severity.WARNING,
                raw_status="Warning",
                message="A volume was skipped because it was offline.",
                error_code=None,
                observed_on=day,
                started_at=datetime(day.year, day.month, day.day, 23, 0),
                finished_at=datetime(day.year, day.month, day.day, 23, 40),
            )
        )
    item = _digest(events).items[0]
    assert item.event.severity == Severity.WARNING
    assert item.severity == Severity.CRITICAL
    assert item.chronic is True
    assert item.escalated is True
    assert item.streak_days == 3


def test_escalation_can_be_disabled() -> None:
    events = []
    for offset in range(3):
        day = date(2026, 10, 12) + timedelta(days=offset)
        events.append(
            event(
                severity=Severity.WARNING,
                raw_status="Warning",
                observed_on=day,
                finished_at=datetime(day.year, day.month, day.day, 2, 1),
            )
        )
    item = _digest(events, escalate=False).items[0]
    assert item.severity == Severity.WARNING
    assert item.chronic is True
    assert item.escalated is False


def test_critical_sorts_ahead_of_a_longer_warning_streak() -> None:
    warning_days = []
    for offset in range(5):
        day = date(2026, 10, 10) + timedelta(days=offset)
        warning_days.append(
            event(
                source="qnap.hbs",
                job_name="Offsite-Photos",
                target="vault-lab.example.internal:/share/photos",
                severity=Severity.WARNING,
                raw_status="Warning",
                message="slow link",
                error_code=None,
                observed_on=day,
                finished_at=datetime(day.year, day.month, day.day, 4, 1),
            )
        )
    critical = event(observed_on=date(2026, 10, 14))
    items = _digest([*warning_days, critical], escalate=False).items
    assert items[0].event.source == "synology.hyper_backup"
    assert items[0].severity == Severity.CRITICAL
    assert items[0].streak_days == 1
    assert items[1].severity == Severity.WARNING
    assert items[1].streak_days == 5


def test_success_today_keeps_a_zero_streak_and_counts_earlier_failures() -> None:
    events = [
        event(
            observed_on=date(2026, 10, 13),
            finished_at=datetime(2026, 10, 13, 2, 1),
            severity=Severity.CRITICAL,
        ),
        event(
            observed_on=date(2026, 10, 14),
            severity=Severity.OK,
            raw_status="Successful",
            message="Backup completed.",
        ),
    ]
    item = _digest(events).items[0]
    assert item.severity == Severity.OK
    assert item.streak_days == 0
    assert item.failures_in_window == 1
    assert item.chronic is False


def test_jobs_without_a_report_today_are_omitted() -> None:
    events = [event(observed_on=date(2026, 10, 13), finished_at=datetime(2026, 10, 13, 2, 1))]
    digest = _digest(events, observed_on=date(2026, 10, 14))
    assert digest.items == ()
    assert digest.summary.critical == 0


def test_later_report_same_day_wins() -> None:
    early = event(finished_at=datetime(2026, 10, 14, 2, 1), message="first")
    late = event(
        finished_at=datetime(2026, 10, 14, 3, 0),
        severity=Severity.OK,
        raw_status="Successful",
        message="retried",
    )
    item = _digest([early, late]).items[0]
    assert item.event.message == "retried"
    assert item.severity == Severity.OK
