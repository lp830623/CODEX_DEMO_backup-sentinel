from datetime import datetime

import pytest

from backup_sentinel.dates import parse_datetime
from backup_sentinel.errors import ParseError
from backup_sentinel.models import Severity
from backup_sentinel.parsers.common import parse_size
from backup_sentinel.status import classify_status


@pytest.mark.parametrize(
    ("raw", "severity"),
    [
        ("Successful", Severity.OK),
        ("Success", Severity.OK),
        ("Completed", Severity.OK),
        ("Finished successfully", Severity.OK),
        ("Warning", Severity.WARNING),
        ("Success with warnings", Severity.WARNING),
        ("Partial", Severity.WARNING),
        ("Queued", Severity.WARNING),
        ("Failed", Severity.CRITICAL),
        ("Error", Severity.CRITICAL),
        ("Completed with errors", Severity.CRITICAL),
        ("Cancelled", Severity.CRITICAL),
        ("Canceled", Severity.CRITICAL),
    ],
)
def test_classify_status(raw: str, severity: Severity) -> None:
    assert classify_status(raw) == severity


def test_classify_empty_status() -> None:
    with pytest.raises(ParseError):
        classify_status("   ")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-14 02:00:11", datetime(2026, 10, 14, 2, 0, 11)),
        ("2026-10-14T02:00:11", datetime(2026, 10, 14, 2, 0, 11)),
        ("2026/10/14 02:00", datetime(2026, 10, 14, 2, 0, 0)),
        ("14.10.2026 22:00:05", datetime(2026, 10, 14, 22, 0, 5)),
        ("10/14/2026 10:00:05 PM", datetime(2026, 10, 14, 22, 0, 5)),
        ("10/14/2026 12:00 AM", datetime(2026, 10, 14, 0, 0, 0)),
        ("13/10/2026 22:00:05", datetime(2026, 10, 13, 22, 0, 5)),
        ("10/13/2026 22:00:05", datetime(2026, 10, 13, 22, 0, 5)),
        ("2026-10-14 02:00:11 UTC", datetime(2026, 10, 14, 2, 0, 11)),
    ],
)
def test_parse_datetime(value: str, expected: datetime) -> None:
    assert parse_datetime(value) == expected


def test_parse_datetime_rejects_unknown() -> None:
    assert parse_datetime("next Tuesday") is None
    assert parse_datetime(None) is None
    assert parse_datetime("   ") is None


def test_parse_size() -> None:
    assert parse_size("0 B") == 0
    assert parse_size("0 bytes") == 0
    assert parse_size("12.4 GB") == int(12.4 * 1024**3)
    assert parse_size("1,024 MB") == 1024 * 1024**2
    assert parse_size("Transferred: 8.6 GB today") == int(8.6 * 1024**3)
    assert parse_size("no size here") is None
    assert parse_size(None) is None
