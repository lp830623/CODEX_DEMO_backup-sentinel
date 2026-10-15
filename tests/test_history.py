from datetime import date, datetime

from backup_sentinel.history import HistoryStore
from backup_sentinel.models import Severity
from tests.support import event


def test_roundtrip_and_replace(tmp_path) -> None:
    store = HistoryStore(tmp_path / "nested" / "history.db")
    original = event()
    store.upsert([original])
    loaded = store.load_between(date(2026, 10, 14), date(2026, 10, 14))
    assert loaded == [original]

    corrected = event(
        severity=Severity.OK,
        raw_status="Successful",
        message="Backup completed.",
        error_code=None,
        finished_at=datetime(2026, 10, 14, 3, 0),
    )
    store.upsert([corrected])
    replaced = store.load_between(date(2026, 10, 1), date(2026, 10, 20))
    assert len(replaced) == 1
    assert replaced[0].severity == Severity.OK
    assert replaced[0].message == "Backup completed."
    assert store.latest_date() == date(2026, 10, 14)


def test_missing_database_reads_as_empty(tmp_path) -> None:
    store = HistoryStore(tmp_path / "missing.db")
    assert store.load_between(date(2026, 10, 1), date(2026, 10, 14)) == []
    assert store.latest_date() is None
    assert not store.path.exists()
