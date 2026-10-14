"""Send the digest as a multipart plain-text and HTML email."""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from email.message import EmailMessage

from backup_sentinel.config import EmailConfig
from backup_sentinel.errors import BackupSentinelError

SmtpFactory = Callable[..., object]


def build_message(
    config: EmailConfig,
    *,
    subject: str,
    text: str,
    html: str,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = config.mail_from
    message["To"] = ", ".join(config.mail_to)
    message["Subject"] = " ".join(subject.split())
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def send_email(
    config: EmailConfig,
    *,
    subject: str,
    text: str,
    html: str,
    client_factory: SmtpFactory | None = None,
    ssl_factory: SmtpFactory | None = None,
) -> None:
    message = build_message(config, subject=subject, text=text, html=html)
    plain_factory = client_factory or smtplib.SMTP
    secure_factory = ssl_factory or client_factory or smtplib.SMTP_SSL
    smtp: object | None = None
    try:
        if config.use_ssl:
            smtp = secure_factory(config.smtp_host, config.smtp_port, timeout=30)
        else:
            smtp = plain_factory(config.smtp_host, config.smtp_port, timeout=30)
            if config.use_tls:
                smtp.starttls()  # type: ignore[attr-defined]
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)  # type: ignore[attr-defined]
        smtp.send_message(message)  # type: ignore[attr-defined]
    except (OSError, smtplib.SMTPException) as exc:
        raise BackupSentinelError(f"email delivery failed: {exc}") from exc
    finally:
        if smtp is not None:
            try:
                smtp.quit()  # type: ignore[attr-defined]
            except (OSError, smtplib.SMTPException):
                pass
