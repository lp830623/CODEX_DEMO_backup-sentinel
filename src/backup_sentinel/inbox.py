"""Find report files and read plain text, HTML, and .eml bodies."""

from __future__ import annotations

import email
from collections.abc import Sequence
from datetime import date
from email.message import Message
from pathlib import Path

from backup_sentinel.config import InputConfig
from backup_sentinel.errors import BackupSentinelError, ConfigError
from backup_sentinel.models import BackupEvent
from backup_sentinel.parsers import parse_report

_SUFFIXES = {".txt", ".html", ".htm", ".eml", ".log"}


def discover_files(inputs: Sequence[InputConfig]) -> list[Path]:
    if not inputs:
        raise ConfigError("no inputs configured; pass --input or set inputs in the config")
    found: list[Path] = []
    for item in inputs:
        if not item.path.exists():
            raise ConfigError(f"input path does not exist: {item.path}")
        if item.path.is_file():
            found.append(item.path)
            continue
        iterator = item.path.rglob("*") if item.recursive else item.path.glob("*")
        for candidate in sorted(iterator):
            if not candidate.is_file():
                continue
            if candidate.name.startswith("."):
                continue
            if candidate.suffix.lower() not in _SUFFIXES:
                continue
            found.append(candidate)
    if not found:
        raise ConfigError("no report files found; check inputs and --input paths")
    return found


def read_report(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if path.suffix.lower() == ".eml":
        return _eml_body(data)
    return data.decode("utf-8")


def parse_files(
    paths: Sequence[Path],
    *,
    fallback_date: date,
) -> tuple[list[BackupEvent], list[str]]:
    events: list[BackupEvent] = []
    notices: list[str] = []
    for path in paths:
        try:
            text = read_report(path)
            events.extend(parse_report(text, fallback_date=fallback_date, source_path=str(path)))
        except BackupSentinelError as exc:
            notices.append(str(exc))
        except UnicodeDecodeError:
            notices.append(f"{path}: file is not valid UTF-8")
    return events, notices


def _eml_body(data: bytes) -> str:
    message = email.message_from_bytes(data)
    if message.is_multipart():
        plain = _parts(message, "plain")
        if plain:
            return "\n".join(plain)
        html = _parts(message, "html")
        if html:
            return "\n".join(html)
        return ""
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    raw = message.get_payload()
    return raw if isinstance(raw, str) else ""


def _parts(message: Message, subtype: str) -> list[str]:
    found: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_subtype() != subtype:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        charset = part.get_content_charset() or "utf-8"
        found.append(payload.decode(charset, errors="replace"))
    return found
