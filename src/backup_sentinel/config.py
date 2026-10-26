"""Load YAML configuration and expand ${VAR} / ${VAR:-default} placeholders."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from backup_sentinel.errors import ConfigError

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_DEFAULT_SUBJECT = "Backup digest {date}: {critical} critical, {warning} warning, {ok} ok"


@dataclass(frozen=True, slots=True)
class InputConfig:
    path: Path
    recursive: bool = True


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    path: Path
    lookback_days: int = 7
    chronic_after_days: int = 3


@dataclass(frozen=True, slots=True)
class EmailConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    use_tls: bool
    use_ssl: bool
    mail_from: str
    mail_to: tuple[str, ...]
    subject: str


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    enabled: bool
    url: str
    timeout_seconds: float
    headers: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class AppConfig:
    inputs: tuple[InputConfig, ...]
    history: HistoryConfig
    email: EmailConfig
    webhook: WebhookConfig
    timezone: str
    escalate_chronic_warnings: bool
    config_path: Path


def load_config(path: Path) -> AppConfig:
    """Load ``path``. Relative paths inside the file resolve next to it."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    data = _expand(raw)
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    base = path.parent
    return AppConfig(
        inputs=_inputs(data.get("inputs", []), base),
        history=_history(data.get("history", {}), base),
        email=_email(data.get("email", {})),
        webhook=_webhook(data.get("webhook", {})),
        timezone=_timezone(data.get("timezone", "UTC")),
        escalate_chronic_warnings=_escalate(data.get("ranking", {})),
        config_path=path,
    )


def _expand(value: object) -> object:
    if isinstance(value, str):
        return _expand_string(value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def _expand_string(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise ConfigError(f"environment variable {name} is not set")

    return _ENV.sub(replace, value)


def _inputs(value: object, base: Path) -> tuple[InputConfig, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("inputs must be a list")
    return tuple(_one_input(item, base) for item in value)


def _one_input(value: object, base: Path) -> InputConfig:
    if isinstance(value, str):
        return InputConfig(path=_resolve(base, value, "inputs path"), recursive=True)
    if isinstance(value, dict):
        recursive = _as_bool(value.get("recursive", True), "inputs.recursive")
        path = _resolve(base, value.get("path"), "inputs.path")
        return InputConfig(path=path, recursive=recursive)
    raise ConfigError("each input must be a path or a mapping with a path")


def _history(value: object, base: Path) -> HistoryConfig:
    if isinstance(value, str):
        path = _resolve(base, value, "history")
        lookback, chronic = 7, 3
    elif isinstance(value, dict):
        path = _resolve(base, value.get("path", "state/history.db"), "history.path")
        lookback = _as_int(value.get("lookback_days", 7), "history.lookback_days")
        chronic = _as_int(value.get("chronic_after_days", 3), "history.chronic_after_days")
    else:
        raise ConfigError("history must be a path or a mapping")
    if lookback < 1:
        raise ConfigError("history.lookback_days must be at least 1")
    if chronic < 1:
        raise ConfigError("history.chronic_after_days must be at least 1")
    if chronic > lookback:
        raise ConfigError("history.chronic_after_days cannot be greater than history.lookback_days")
    return HistoryConfig(path=path, lookback_days=lookback, chronic_after_days=chronic)


def _timezone(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("timezone must be a string")
    name = value.strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"unknown timezone: {name}") from exc
    return name


def _escalate(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        raise ConfigError("ranking must be a mapping")
    return _as_bool(
        value.get("escalate_chronic_warnings", True),
        "ranking.escalate_chronic_warnings",
    )


def _email(value: object) -> EmailConfig:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigError("email must be a mapping")
    enabled = _as_bool(value.get("enabled", False), "email.enabled")
    host = _string(value.get("smtp_host", ""), "email.smtp_host")
    port = _as_int(value.get("smtp_port", 587), "email.smtp_port")
    username = _string(value.get("smtp_username", ""), "email.smtp_username")
    password = _string(value.get("smtp_password", ""), "email.smtp_password")
    use_tls = _as_bool(value.get("use_tls", True), "email.use_tls")
    use_ssl = _as_bool(value.get("use_ssl", False), "email.use_ssl")
    mail_from = _string(value.get("from", ""), "email.from")
    subject = _string(value.get("subject", _DEFAULT_SUBJECT), "email.subject")
    recipients = _recipients(value.get("to", [])) if "to" in value else ()
    if enabled:
        if not host:
            raise ConfigError("email.smtp_host is required when email is enabled")
        if not 1 <= port <= 65535:
            raise ConfigError("email.smtp_port must be between 1 and 65535")
        if use_tls and use_ssl:
            raise ConfigError("email.use_tls and email.use_ssl cannot both be true")
        _no_newline(host, "email.smtp_host")
        _no_newline(mail_from, "email.from")
        if "@" not in mail_from:
            raise ConfigError("email.from must be an email address")
        if not recipients:
            raise ConfigError("email.to needs at least one recipient when email is enabled")
        for recipient in recipients:
            if "@" not in recipient:
                raise ConfigError(f"email recipient {recipient!r} is not an email address")
    return EmailConfig(
        enabled=enabled,
        smtp_host=host,
        smtp_port=port,
        smtp_username=username,
        smtp_password=password,
        use_tls=use_tls,
        use_ssl=use_ssl,
        mail_from=mail_from,
        mail_to=recipients,
        subject=subject,
    )


def _webhook(value: object) -> WebhookConfig:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigError("webhook must be a mapping")
    enabled = _as_bool(value.get("enabled", False), "webhook.enabled")
    url = _string(value.get("url", ""), "webhook.url")
    timeout = _as_float(value.get("timeout_seconds", 10), "webhook.timeout_seconds")
    headers = _headers(value.get("headers", {}))
    if enabled:
        _no_newline(url, "webhook.url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError("webhook.url must be an http or https URL")
        if timeout <= 0:
            raise ConfigError("webhook.timeout_seconds must be greater than 0")
    return WebhookConfig(enabled=enabled, url=url, timeout_seconds=timeout, headers=headers)


def _headers(value: object) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ConfigError("webhook.headers must be a mapping")
    headers: list[tuple[str, str]] = []
    for key, raw in value.items():
        if not isinstance(key, str) or not isinstance(raw, str):
            raise ConfigError("webhook headers must be strings")
        _no_newline(key, "webhook header name")
        _no_newline(raw, f"webhook header {key}")
        headers.append((key, raw))
    return tuple(headers)


def _recipients(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, list):
        parts = []
        for item in value:
            if not isinstance(item, str):
                raise ConfigError("email recipients must be strings")
            parts.extend(item.split(","))
    else:
        raise ConfigError("email.to must be a string or a list")
    return tuple(_no_newline(part.strip(), "email recipient") for part in parts if part.strip())


def _resolve(base: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a path")
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _string(value: object, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a string")
    return value


def _as_bool(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"{field} must be a boolean")


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise ConfigError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ConfigError(f"{field} must be an integer") from exc
    raise ConfigError(f"{field} must be an integer")


def _as_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{field} must be a number")
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{field} must be a number") from exc


def _no_newline(value: str, field: str) -> str:
    if "\n" in value or "\r" in value:
        raise ConfigError(f"{field} contains a newline")
    return value
