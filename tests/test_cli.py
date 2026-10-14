import json
import subprocess
import sys
from pathlib import Path

import pytest

from backup_sentinel.cli import main

HYPER_OK = """\
Hyper Backup

Task: Quiet-Job
Backup destination: vault-lab.example.internal
Status: Successful
Start time: 2026-10-14 01:00:00
End time: 2026-10-14 01:10:00
Message: Backup completed.
"""

HYPER_WARN = """\
Hyper Backup

Task: Quiet-Job
Backup destination: vault-lab.example.internal
Status: Warning
Start time: 2026-10-14 01:00:00
End time: 2026-10-14 01:10:00
Message: One folder was skipped.
"""


def _config(tmp_path: Path, samples: Path | None = None) -> Path:
    history = tmp_path / "history.db"
    if samples is None:
        inputs = "inputs: []\n"
    else:
        inputs = f"inputs:\n  - path: {json.dumps(str(samples))}\n    recursive: true\n"
    path = tmp_path / "config.yaml"
    path.write_text(
        "timezone: UTC\n"
        f"{inputs}"
        "history:\n"
        f"  path: {json.dumps(str(history))}\n"
        "  lookback_days: 7\n"
        "  chronic_after_days: 3\n"
        "ranking:\n"
        "  escalate_chronic_warnings: true\n",
        encoding="utf-8",
    )
    return path


def test_three_day_story(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path, repo_root / "samples")
    assert main(["run", "--config", str(config), "--date", "2026-10-14", "--format", "json"]) == 0
    captured = capsys.readouterr()
    assert "delivery: email disabled" in captured.err
    assert "delivery: webhook disabled" in captured.err
    payload = json.loads(captured.out)
    assert payload["date"] == "2026-10-14"
    assert payload["summary"] == {"critical": 3, "warning": 2, "ok": 2, "chronic": 2}
    items = payload["items"]
    keys = [
        (item["event"]["source"], item["event"]["job_name"], item["event"]["target"])
        for item in items
    ]
    assert keys == [
        ("synology.hyper_backup", "Documents-Daily", "vault-lab.example.internal"),
        ("veeam.backup", "Nightly-VM-Backup", "vm-db-01"),
        ("synology.snapshot", "Volume-Replica", "dr-lab.example.internal"),
        ("synology.active_backup", "Fileserver-Lab", "fileserver-lab"),
        ("veeam.backup", "Nightly-VM-Backup", "vm-app-01"),
        ("qnap.hbs", "Offsite-Photos", "vault-lab.example.internal:/share/photos"),
        ("veeam.backup", "Nightly-VM-Backup", "vm-web-01"),
    ]
    by_target = {item["event"]["target"]: item for item in items}
    documents = by_target["vault-lab.example.internal"]
    assert documents["streak_days"] == 3
    assert documents["failures_in_window"] == 3
    assert documents["chronic"] is True
    assert documents["escalated"] is False
    assert documents["event"]["error_code"] == "31"
    database = by_target["vm-db-01"]
    assert database["streak_days"] == 3 and database["chronic"] is True
    app = by_target["vm-app-01"]
    assert app["severity"] == "warning"
    assert app["streak_days"] == 1
    assert app["failures_in_window"] == 2
    photos = by_target["vault-lab.example.internal:/share/photos"]
    assert photos["severity"] == "ok"
    assert photos["streak_days"] == 0
    assert photos["failures_in_window"] == 1
    web = by_target["vm-web-01"]
    assert web["severity"] == "ok" and web["failures_in_window"] == 0
    fileserver = by_target["fileserver-lab"]
    assert fileserver["streak_days"] == 2 and fileserver["severity"] == "warning"
    replica = by_target["dr-lab.example.internal"]
    assert (
        replica["severity"] == "critical"
        and replica["streak_days"] == 1
        and replica["chronic"] is False
    )


def test_story_text_mentions_chronic_and_recovered_jobs(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path, repo_root / "samples")
    assert main(["run", "--config", str(config), "--date", "2026-10-14"]) == 0
    text = capsys.readouterr().out
    assert "Synology Hyper Backup · Documents-Daily → vault-lab.example.internal" in text
    assert "3-day streak" in text
    assert "· chronic" in text
    assert "Changed block tracking is disabled" in text
    assert "1 failure in 7 days" in text
    assert "vm-web-01" in text
    assert "escalated" not in text
    assert "No backup reports" not in text


def test_sequential_days_persist_in_history(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path)
    samples = repo_root / "samples"
    for day in ("2026-10-12", "2026-10-13"):
        assert (
            main(
                [
                    "run",
                    "--config",
                    str(config),
                    "--input",
                    str(samples / day),
                    "--date",
                    day,
                ]
            )
            == 0
        )
        capsys.readouterr()
    assert (
        main(
            [
                "run",
                "--config",
                str(config),
                "--input",
                str(samples / "2026-10-14"),
                "--date",
                "2026-10-14",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    documents = next(
        item for item in payload["items"] if item["event"]["job_name"] == "Documents-Daily"
    )
    assert documents["streak_days"] == 3
    assert (tmp_path / "history.db").exists()

    capsys.readouterr()
    assert main(["report", "--config", str(config), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["date"] == "2026-10-14"
    assert report["summary"]["critical"] == 3


def test_dry_run_does_not_write_history_or_send(
    tmp_path: Path,
    repo_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"email": 0, "webhook": 0}

    def fail_email(*_args: object, **_kwargs: object) -> None:
        called["email"] += 1
        raise AssertionError("email should not be sent")

    def fail_webhook(*_args: object, **_kwargs: object) -> None:
        called["webhook"] += 1
        raise AssertionError("webhook should not be posted")

    monkeypatch.setattr("backup_sentinel.delivery.email.send_email", fail_email)
    monkeypatch.setattr("backup_sentinel.delivery.webhook.post_json", fail_webhook)
    config = _config(tmp_path, repo_root / "samples")
    assert (
        main(
            [
                "run",
                "--config",
                str(config),
                "--date",
                "2026-10-14",
                "--format",
                "json",
                "--dry-run",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "dry-run" in captured.err
    payload = json.loads(captured.out)
    assert payload["summary"]["chronic"] == 2
    assert not (tmp_path / "history.db").exists()
    assert called == {"email": 0, "webhook": 0}


def test_latest_ingested_date_is_the_default(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path, repo_root / "samples")
    assert main(["run", "--config", str(config), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["date"] == "2026-10-14"


def test_fail_on_critical_exits_2(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path, repo_root / "samples")
    code = main(["run", "--config", str(config), "--date", "2026-10-14", "--fail-on", "critical"])
    assert code == 2
    assert "CRITICAL" in capsys.readouterr().out


def test_fail_on_thresholds_for_a_single_job(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "ok.txt").write_text(HYPER_OK, encoding="utf-8")
    config = _config(tmp_path)
    assert (
        main(["run", "--config", str(config), "--input", str(inbox), "--fail-on", "critical"]) == 0
    )
    capsys.readouterr()
    assert (
        main(["run", "--config", str(config), "--input", str(inbox), "--fail-on", "warning"]) == 0
    )
    capsys.readouterr()
    (inbox / "ok.txt").write_text(HYPER_WARN, encoding="utf-8")
    assert (
        main(["run", "--config", str(config), "--input", str(inbox), "--fail-on", "critical"]) == 0
    )
    capsys.readouterr()
    assert (
        main(["run", "--config", str(config), "--input", str(inbox), "--fail-on", "warning"]) == 2
    )


def test_unrecognized_file_is_skipped_and_a_useless_inbox_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "notes.txt").write_text("hello from the operator\n", encoding="utf-8")
    (inbox / "job.txt").write_text(HYPER_OK, encoding="utf-8")
    config = _config(tmp_path)
    assert main(["run", "--config", str(config), "--input", str(inbox), "--format", "json"]) == 0
    captured = capsys.readouterr()
    assert "unrecognized backup report" in captured.err
    payload = json.loads(captured.out)
    assert payload["summary"]["ok"] == 1

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    empty = fresh / "inbox"
    empty.mkdir()
    (empty / "notes.txt").write_text("still not a backup report\n", encoding="utf-8")
    code = main(
        ["run", "--config", str(_config(fresh)), "--input", str(empty), "--date", "2026-10-14"]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "no recognized backup reports were ingested" in captured.err
    assert "No backup reports for this date." in captured.out


def test_webhook_and_email_are_called_with_the_digest(
    tmp_path: Path,
    repo_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    def fake_email(_config: object, *, subject: str, text: str, html: str) -> None:
        sent["subject"] = subject
        sent["text"] = text
        sent["html"] = html

    def fake_webhook(
        url: str, payload: dict[str, object], headers: dict[str, str], timeout: float
    ) -> int:
        sent["url"] = url
        sent["payload"] = payload
        sent["headers"] = headers
        sent["timeout"] = timeout
        return 202

    monkeypatch.setattr("backup_sentinel.delivery.email.send_email", fake_email)
    monkeypatch.setattr("backup_sentinel.delivery.webhook.post_json", fake_webhook)
    path = tmp_path / "config.yaml"
    path.write_text(
        "timezone: UTC\n"
        "inputs:\n"
        f"  - path: {json.dumps(str(repo_root / 'samples'))}\n"
        "history:\n"
        f"  path: {json.dumps(str(tmp_path / 'history.db'))}\n"
        "email:\n"
        "  enabled: true\n"
        "  smtp_host: localhost\n"
        "  from: sentinel@example.invalid\n"
        "  to: ops@example.invalid\n"
        '  subject: "Digest {date} {critical}/{warning}/{ok}"\n'
        "webhook:\n"
        "  enabled: true\n"
        "  url: https://hooks.example.invalid/backup-sentinel\n"
        "  headers:\n"
        "    Authorization: Bearer example-token\n",
        encoding="utf-8",
    )
    assert main(["run", "--config", str(path), "--date", "2026-10-14", "--format", "text"]) == 0
    captured = capsys.readouterr()
    assert "delivery: email sent to ops@example.invalid" in captured.err
    assert "delivery: webhook posted (202)" in captured.err
    assert sent["subject"] == "Digest 2026-10-14 3/2/2"
    assert "Documents-Daily" in str(sent["text"])
    assert "Documents-Daily" in str(sent["html"])
    payload = sent["payload"]
    assert isinstance(payload, dict)
    assert payload["summary"]["critical"] == 3
    assert sent["url"] == "https://hooks.example.invalid/backup-sentinel"
    assert sent["headers"] == {"Authorization": "Bearer example-token"}


def test_parse_and_sources_commands(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = repo_root / "samples/2026-10-14/hyper-backup.txt"
    assert main(["parse", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["job_name"] == "Documents-Daily"
    assert payload[0]["severity"] == "critical"

    assert main(["sources"]) == 0
    text = capsys.readouterr().out
    for source in (
        "synology.hyper_backup",
        "synology.active_backup",
        "synology.snapshot",
        "veeam.backup",
        "qnap.hbs",
    ):
        assert source in text


def test_invalid_date_and_missing_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path)
    assert main(["run", "--config", str(config), "--date", "14-10-2026"]) == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err
    assert main(["run", "--config", str(tmp_path / "missing.yaml")]) == 1


def test_version_and_module_help() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    completed = subprocess.run(
        [sys.executable, "-m", "backup_sentinel", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "daily digest" in completed.stdout.casefold()
