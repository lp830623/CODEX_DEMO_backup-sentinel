import json
import smtplib
import urllib.error

import pytest

from backup_sentinel.config import EmailConfig
from backup_sentinel.delivery.email import build_message, send_email
from backup_sentinel.delivery.webhook import post_json
from backup_sentinel.errors import BackupSentinelError


def _email_config() -> EmailConfig:
    return EmailConfig(
        enabled=True,
        smtp_host="localhost",
        smtp_port=587,
        smtp_username="sentinel",
        smtp_password="secret",
        use_tls=True,
        use_ssl=False,
        mail_from="sentinel@example.invalid",
        mail_to=("ops@example.invalid", "oncall@example.invalid"),
        subject="Backup digest",
    )


class FakeSMTP:
    def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: list[object] = []
        self.quit_called = False

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: object) -> None:
        self.sent.append(message)

    def quit(self) -> None:
        self.quit_called = True


def test_send_email_uses_starttls_and_builds_both_bodies() -> None:
    created: list[FakeSMTP] = []

    def factory(host: str, port: int, timeout: int | None = None) -> FakeSMTP:
        client = FakeSMTP(host, port, timeout)
        created.append(client)
        return client

    send_email(
        _email_config(),
        subject="Digest\nline",
        text="hello plain",
        html="<p>hello</p>",
        client_factory=factory,
    )
    client = created[0]
    assert client.host == "localhost"
    assert client.port == 587
    assert client.started_tls is True
    assert client.logged_in == ("sentinel", "secret")
    assert client.quit_called is True
    message = client.sent[0]
    assert message["Subject"] == "Digest line"  # type: ignore[index]
    assert message["From"] == "sentinel@example.invalid"  # type: ignore[index]
    assert "ops@example.invalid" in message["To"]  # type: ignore[index]
    plain = message.get_body(preferencelist=("plain",)).get_content()  # type: ignore[attr-defined]
    html = message.get_body(preferencelist=("html",)).get_content()  # type: ignore[attr-defined]
    assert "hello plain" in plain
    assert "hello" in html


def test_smtp_failure_is_reported_and_the_connection_closes() -> None:
    created: list[FakeSMTP] = []

    class Boom(FakeSMTP):
        def send_message(self, message: object) -> None:
            raise smtplib.SMTPException("relay denied")

    def factory(host: str, port: int, timeout: int | None = None) -> Boom:
        client = Boom(host, port, timeout)
        created.append(client)
        return client

    with pytest.raises(BackupSentinelError, match="relay denied"):
        send_email(
            _email_config(),
            subject="Digest",
            text="plain",
            html="<p>html</p>",
            client_factory=factory,
        )
    assert created[0].quit_called is True


def test_build_message_strips_subject_newlines() -> None:
    message = build_message(_email_config(), subject="one\r\ntwo", text="plain", html="<p>x</p>")
    assert message["Subject"] == "one two"


def test_post_json_sets_content_type_and_user_headers() -> None:
    seen: dict[str, object] = {}

    class Response:
        status = 204

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

    def opener(request: object, timeout: float) -> Response:
        seen["url"] = request.full_url  # type: ignore[attr-defined]
        seen["body"] = json.loads(request.data.decode())  # type: ignore[attr-defined]
        seen["type"] = request.get_header("Content-type")  # type: ignore[attr-defined]
        seen["agent"] = request.get_header("User-agent")  # type: ignore[attr-defined]
        seen["auth"] = request.get_header("Authorization")  # type: ignore[attr-defined]
        seen["timeout"] = timeout
        return Response()

    status = post_json(
        "https://hooks.example.invalid/backup-sentinel",
        {"date": "2026-10-14"},
        {"Authorization": "Bearer example-token"},
        5,
        opener=opener,
    )
    assert status == 204
    assert seen["url"] == "https://hooks.example.invalid/backup-sentinel"
    assert seen["body"] == {"date": "2026-10-14"}
    assert seen["type"] == "application/json"
    assert seen["auth"] == "Bearer example-token"
    assert "backup-sentinel/" in str(seen["agent"])
    assert seen["timeout"] == 5


def test_webhook_errors_are_wrapped() -> None:
    def opener(_request: object, timeout: float) -> object:
        raise urllib.error.URLError(f"down after {timeout}s")

    with pytest.raises(BackupSentinelError, match="webhook delivery failed"):
        post_json("https://hooks.example.invalid/hook", {}, {}, 1, opener=opener)
