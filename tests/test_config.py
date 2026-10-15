from pathlib import Path

import pytest

from backup_sentinel.config import load_config
from backup_sentinel.errors import ConfigError


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_example_config_loads_without_environment(repo_root: Path) -> None:
    config = load_config(repo_root / "config.example.yaml")
    assert config.email.enabled is False
    assert config.email.smtp_host == "localhost"
    assert config.email.smtp_port == 587
    assert config.email.mail_to == ("ops@example.invalid",)
    assert config.webhook.enabled is False
    assert config.webhook.url == "https://hooks.example.invalid/backup-sentinel"
    assert config.history.lookback_days == 7
    assert config.history.chronic_after_days == 3
    assert config.escalate_chronic_warnings is True
    assert config.timezone == "UTC"
    assert config.inputs[0].path == (repo_root / "samples").resolve()
    assert config.inputs[0].recursive is True
    assert config.history.path == (repo_root / "state" / "history.db").resolve()


def test_environment_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "mail.example.internal")
    monkeypatch.setenv("SMTP_TO", "a@example.invalid, b@example.invalid")
    path = _write(
        tmp_path / "config.yaml",
        """\
email:
  enabled: false
  smtp_host: "${SMTP_HOST:-localhost}"
  to: "${SMTP_TO:-ops@example.invalid}"
""",
    )
    config = load_config(path)
    assert config.email.smtp_host == "mail.example.internal"
    assert config.email.mail_to == ("a@example.invalid", "b@example.invalid")


def test_missing_environment_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    path = _write(
        tmp_path / "config.yaml",
        """\
webhook:
  enabled: true
  url: "${WEBHOOK_URL}/hook"
""",
    )
    with pytest.raises(ConfigError, match="WEBHOOK_URL"):
        load_config(path)


def test_chronic_threshold_cannot_exceed_lookback(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "config.yaml",
        """\
history:
  path: state/history.db
  lookback_days: 2
  chronic_after_days: 5
""",
    )
    with pytest.raises(ConfigError, match="chronic_after_days"):
        load_config(path)


def test_unknown_timezone(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.yaml", "timezone: Not/AZone\n")
    with pytest.raises(ConfigError, match="timezone"):
        load_config(path)


def test_enabled_email_requires_a_host(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "config.yaml",
        """\
email:
  enabled: true
  smtp_host: ""
  from: sentinel@example.invalid
  to: ops@example.invalid
""",
    )
    with pytest.raises(ConfigError, match="smtp_host"):
        load_config(path)


def test_email_rejects_newline_in_recipient(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "config.yaml",
        """\
email:
  enabled: true
  smtp_host: localhost
  from: sentinel@example.invalid
  to: "ops@example.invalid\\nBcc: injected@example.invalid"
""",
    )
    with pytest.raises(ConfigError, match="newline"):
        load_config(path)


def test_tls_and_ssl_are_mutually_exclusive(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "config.yaml",
        """\
email:
  enabled: true
  smtp_host: localhost
  use_tls: true
  use_ssl: true
  from: sentinel@example.invalid
  to: ops@example.invalid
""",
    )
    with pytest.raises(ConfigError, match="use_ssl"):
        load_config(path)


def test_webhook_requires_http_url(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "config.yaml",
        """\
webhook:
  enabled: true
  url: file:///tmp/hook
""",
    )
    with pytest.raises(ConfigError, match="webhook.url"):
        load_config(path)


def test_relative_paths_resolve_beside_the_config(tmp_path: Path) -> None:
    directory = tmp_path / "nested"
    directory.mkdir()
    path = _write(
        directory / "config.yaml",
        """\
inputs:
  - path: inbox
    recursive: false
history:
  path: data/history.db
""",
    )
    config = load_config(path)
    assert config.inputs[0].path == (directory / "inbox").resolve()
    assert config.inputs[0].recursive is False
    assert config.history.path == (directory / "data" / "history.db").resolve()


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_version_matches_pyproject(repo_root: Path) -> None:
    import tomllib

    from backup_sentinel import __version__

    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__
