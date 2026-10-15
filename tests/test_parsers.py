from datetime import date, datetime

import pytest

from backup_sentinel.errors import ParseError, UnrecognizedReportError
from backup_sentinel.inbox import read_report
from backup_sentinel.models import Severity
from backup_sentinel.parsers import parse_report

CASES = [
    (
        "samples/2026-10-12/hyper-backup.txt",
        [
            (
                "synology.hyper_backup",
                "Documents-Daily",
                "vault-lab.example.internal",
                "critical",
                "2026-10-12",
            )
        ],
    ),
    (
        "samples/2026-10-12/active-backup.txt",
        [("synology.active_backup", "Fileserver-Lab", "fileserver-lab", "ok", "2026-10-12")],
    ),
    (
        "samples/2026-10-12/snapshot.txt",
        [("synology.snapshot", "Volume-Replica", "dr-lab.example.internal", "ok", "2026-10-12")],
    ),
    (
        "samples/2026-10-12/veeam.txt",
        [
            ("veeam.backup", "Nightly-VM-Backup", "vm-web-01", "ok", "2026-10-12"),
            ("veeam.backup", "Nightly-VM-Backup", "vm-app-01", "warning", "2026-10-12"),
            ("veeam.backup", "Nightly-VM-Backup", "vm-db-01", "critical", "2026-10-12"),
        ],
    ),
    (
        "samples/2026-10-12/qnap-hbs.txt",
        [
            (
                "qnap.hbs",
                "Offsite-Photos",
                "vault-lab.example.internal:/share/photos",
                "ok",
                "2026-10-12",
            )
        ],
    ),
    (
        "samples/2026-10-13/hyper-backup.txt",
        [
            (
                "synology.hyper_backup",
                "Documents-Daily",
                "vault-lab.example.internal",
                "critical",
                "2026-10-13",
            )
        ],
    ),
    (
        "samples/2026-10-13/active-backup.eml",
        [("synology.active_backup", "Fileserver-Lab", "fileserver-lab", "warning", "2026-10-13")],
    ),
    (
        "samples/2026-10-13/snapshot.txt",
        [("synology.snapshot", "Volume-Replica", "dr-lab.example.internal", "ok", "2026-10-13")],
    ),
    (
        "samples/2026-10-13/veeam.txt",
        [
            ("veeam.backup", "Nightly-VM-Backup", "vm-web-01", "ok", "2026-10-13"),
            ("veeam.backup", "Nightly-VM-Backup", "vm-app-01", "ok", "2026-10-13"),
            ("veeam.backup", "Nightly-VM-Backup", "vm-db-01", "critical", "2026-10-13"),
        ],
    ),
    (
        "samples/2026-10-13/qnap-hbs.txt",
        [
            (
                "qnap.hbs",
                "Offsite-Photos",
                "vault-lab.example.internal:/share/photos",
                "critical",
                "2026-10-13",
            )
        ],
    ),
    (
        "samples/2026-10-14/hyper-backup.txt",
        [
            (
                "synology.hyper_backup",
                "Documents-Daily",
                "vault-lab.example.internal",
                "critical",
                "2026-10-14",
            )
        ],
    ),
    (
        "samples/2026-10-14/active-backup.txt",
        [("synology.active_backup", "Fileserver-Lab", "fileserver-lab", "warning", "2026-10-14")],
    ),
    (
        "samples/2026-10-14/snapshot.txt",
        [
            (
                "synology.snapshot",
                "Volume-Replica",
                "dr-lab.example.internal",
                "critical",
                "2026-10-14",
            )
        ],
    ),
    (
        "samples/2026-10-14/veeam.html",
        [
            ("veeam.backup", "Nightly-VM-Backup", "vm-web-01", "ok", "2026-10-14"),
            ("veeam.backup", "Nightly-VM-Backup", "vm-app-01", "warning", "2026-10-14"),
            ("veeam.backup", "Nightly-VM-Backup", "vm-db-01", "critical", "2026-10-14"),
        ],
    ),
    (
        "samples/2026-10-14/qnap-hbs.txt",
        [
            (
                "qnap.hbs",
                "Offsite-Photos",
                "vault-lab.example.internal:/share/photos",
                "ok",
                "2026-10-14",
            )
        ],
    ),
]


@pytest.mark.parametrize(("relative", "expected"), CASES, ids=[case[0] for case in CASES])
def test_sample_reports(
    relative: str, expected: list[tuple[str, str, str, str, str]], repo_root
) -> None:
    path = repo_root / relative
    events = parse_report(read_report(path), fallback_date=date(2026, 10, 1), source_path=str(path))
    got = [
        (
            event.source,
            event.job_name,
            event.target,
            event.severity.value,
            event.observed_on.isoformat(),
        )
        for event in events
    ]
    assert got == expected


def test_hyper_backup_failure_fields(repo_root) -> None:
    path = repo_root / "samples/2026-10-14/hyper-backup.txt"
    event = parse_report(read_report(path), fallback_date=date(2026, 10, 1), source_path=str(path))[
        0
    ]
    assert event.error_code == "31"
    assert event.message == "The backup destination is offline."
    assert event.bytes_transferred == 0
    assert event.finished_at == datetime(2026, 10, 14, 2, 1, 6)


def test_veeam_html_splits_objects_and_keeps_healthy_rows(repo_root) -> None:
    path = repo_root / "samples/2026-10-14/veeam.html"
    events = {
        event.target: event
        for event in parse_report(
            read_report(path), fallback_date=date(2026, 10, 1), source_path=str(path)
        )
    }
    assert events["vm-web-01"].severity == Severity.OK
    assert events["vm-web-01"].message == ""
    assert events["vm-web-01"].bytes_transferred == int(12.4 * 1024**3)
    assert events["vm-web-01"].started_at == datetime(2026, 10, 14, 22, 0, 5)
    assert events["vm-db-01"].message == "Production datastore is inaccessible"
    assert events["vm-db-01"].finished_at == datetime(2026, 10, 14, 22, 51, 44)
    assert events["vm-app-01"].severity == Severity.WARNING


def test_qnap_failure_fields(repo_root) -> None:
    path = repo_root / "samples/2026-10-13/qnap-hbs.txt"
    event = parse_report(read_report(path), fallback_date=date(2026, 10, 1), source_path=str(path))[
        0
    ]
    assert event.error_code == "NET_UNREACHABLE"
    assert event.message == "Connection to the remote server failed."
    assert event.bytes_transferred == 0


def test_snapshot_failure_message(repo_root) -> None:
    path = repo_root / "samples/2026-10-14/snapshot.txt"
    event = parse_report(read_report(path), fallback_date=date(2026, 10, 1), source_path=str(path))[
        0
    ]
    assert "timed out" in event.message


def test_prose_hyper_backup_subject_line() -> None:
    text = """\
Hyper Backup

Backup task [Documents-Daily] failed.

Destination: vault-lab.example.internal
Start time: 2026-10-14 02:00:11
"""
    event = parse_report(text, fallback_date=date(2026, 10, 1), source_path="prose.txt")[0]
    assert event.job_name == "Documents-Daily"
    assert event.severity == Severity.CRITICAL
    assert event.target == "vault-lab.example.internal"
    assert event.observed_on == date(2026, 10, 14)


def test_veeam_job_without_objects_uses_european_timestamps() -> None:
    text = """\
Veeam Backup & Replication

Job: Nightly-VM-Backup
Result: Failed
Session start: 14.10.2026 22:00:05
Session end: 14.10.2026 22:18:44
Error: Production datastore is inaccessible.
"""
    event = parse_report(text, fallback_date=date(2026, 10, 1))[0]
    assert event.target == ""
    assert event.severity == Severity.CRITICAL
    assert event.observed_on == date(2026, 10, 14)
    assert event.finished_at == datetime(2026, 10, 14, 22, 18, 44)
    assert event.message == "Production datastore is inaccessible."


def test_veeam_object_names_may_contain_spaces() -> None:
    text = """\
Veeam Backup & Replication

Job: Nightly-VM-Backup
Result: Warning
Session start: 2026-10-14 22:00:00
Session end: 2026-10-14 22:10:00

vm app 01 | Warning | 1 GB | Changed block tracking is disabled
"""
    event = parse_report(text, fallback_date=date(2026, 10, 1))[0]
    assert event.target == "vm app 01"
    assert event.severity == Severity.WARNING


def test_multipart_eml_prefers_plain_text(tmp_path) -> None:
    path = tmp_path / "notice.eml"
    path.write_text(
        "\n".join(
            [
                "From: nas-lab-01@example.internal",
                "To: ops@example.invalid",
                "Subject: Active Backup for Business",
                "MIME-Version: 1.0",
                'Content-Type: multipart/alternative; boundary="bound"',
                "",
                "--bound",
                'Content-Type: text/plain; charset="utf-8"',
                "",
                "Active Backup for Business",
                "",
                "Task: Fileserver-Lab",
                "Device: fileserver-lab",
                "Status: Warning",
                "Start time: 2026-10-13 23:00:00",
                "End time: 2026-10-13 23:10:00",
                "Message: A volume was skipped because it was offline.",
                "",
                "--bound",
                'Content-Type: text/html; charset="utf-8"',
                "",
                "<html><body><p>ignore this html part</p></body></html>",
                "--bound--",
                "",
            ]
        ),
        encoding="utf-8",
    )
    event = parse_report(read_report(path), fallback_date=date(2026, 10, 1), source_path=str(path))[
        0
    ]
    assert event.severity == Severity.WARNING
    assert event.message == "A volume was skipped because it was offline."
    assert "ignore this html" not in event.message


def test_hbs3_signature_without_the_long_product_name() -> None:
    text = "HBS 3\n\nJob name: Offsite-Photos\nStatus: Completed\n"
    event = parse_report(text, fallback_date=date(2026, 10, 14))[0]
    assert event.source == "qnap.hbs"
    assert event.severity == Severity.OK
    assert event.observed_on == date(2026, 10, 14)


def test_missing_job_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="missing job name"):
        parse_report("Hyper Backup\nStatus: Failed\n", fallback_date=date(2026, 10, 14))


def test_unrecognized_report() -> None:
    with pytest.raises(UnrecognizedReportError, match="notes.txt"):
        parse_report(
            "weekly status meeting notes\n",
            fallback_date=date(2026, 10, 14),
            source_path="notes.txt",
        )


def test_long_message_is_clipped() -> None:
    text = "Hyper Backup\nTask: Documents-Daily\nStatus: Failed\nError: " + ("x" * 600) + "\n"
    event = parse_report(text, fallback_date=date(2026, 10, 14))[0]
    assert len(event.message) == 500
    assert event.message.endswith("...")
