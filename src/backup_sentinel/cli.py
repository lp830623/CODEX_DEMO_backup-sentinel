"""Command line interface for backup-sentinel."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from backup_sentinel import __version__
from backup_sentinel.config import AppConfig, load_config
from backup_sentinel.errors import BackupSentinelError, ConfigError
from backup_sentinel.inbox import read_report
from backup_sentinel.models import PRODUCT_LABELS
from backup_sentinel.parsers import PARSERS, parse_report
from backup_sentinel.pipeline import execute
from backup_sentinel.render import event_payload

_EPILOG = """\
examples:
  backup-sentinel run --config config.example.yaml --date 2026-10-14
  backup-sentinel parse samples/2026-10-14/hyper-backup.txt
  backup-sentinel report --config config.yaml --date 2026-10-14 --dry-run
"""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BackupSentinelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup-sentinel",
        description=(
            "Turn Synology, Veeam, and QNAP backup reports into one daily digest ranked by urgency."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"backup-sentinel {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Ingest reports and print the daily digest")
    _add_digest_flags(run)
    run.add_argument(
        "--input",
        action="append",
        default=None,
        metavar="PATH",
        help="Report file or directory. Repeat to pass more than one. Replaces config inputs.",
    )
    run.set_defaults(func=_cmd_run)

    report = commands.add_parser("report", help="Print a digest from history without ingesting")
    _add_digest_flags(report)
    report.set_defaults(func=_cmd_report)

    parse = commands.add_parser("parse", help="Parse one report and print normalized JSON")
    parse.add_argument("file", help="Path to a .txt, .html, or .eml report")
    parse.add_argument(
        "--date",
        help="Calendar date used when the report has no timestamp (YYYY-MM-DD)",
    )
    parse.set_defaults(func=_cmd_parse)

    sources = commands.add_parser("sources", help="List supported backup products")
    sources.set_defaults(func=_cmd_sources)
    return parser


def _add_digest_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, help="Path to a YAML config file")
    parser.add_argument(
        "--date",
        help="Digest date YYYY-MM-DD. Defaults to the latest ingested report date.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Stdout format. Delivery still sends text and HTML mail, and JSON to webhooks.",
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "warning", "critical"),
        default="none",
        help="Exit 2 when the digest meets this urgency. Delivery errors still exit 1.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the digest without writing history or sending email or webhooks.",
    )


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    return _emit(
        config,
        command="run",
        digest_date=_parse_date(args.date),
        dry_run=args.dry_run,
        fail_on=args.fail_on,
        output_format=args.format,
        input_paths=[Path(value) for value in args.input] if args.input else None,
    )


def _cmd_report(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    return _emit(
        config,
        command="report",
        digest_date=_parse_date(args.date),
        dry_run=args.dry_run,
        fail_on=args.fail_on,
        output_format=args.format,
        input_paths=None,
    )


def _cmd_parse(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise ConfigError(f"file not found: {path}")
    fallback = _parse_date(args.date) or date.today()
    events = parse_report(read_report(path), fallback_date=fallback, source_path=str(path))
    print(json.dumps([event_payload(event) for event in events], indent=2, ensure_ascii=False))
    return 0


def _cmd_sources(_args: argparse.Namespace) -> int:
    for parser in PARSERS:
        label = PRODUCT_LABELS[parser.source]
        print(f"{parser.source}  {label}  [{parser.signature}]")
    return 0


def _emit(
    config: AppConfig,
    *,
    command: str,
    digest_date: date | None,
    dry_run: bool,
    fail_on: str,
    output_format: str,
    input_paths: list[Path] | None,
) -> int:
    result = execute(
        config,
        command=command,
        digest_date=digest_date,
        dry_run=dry_run,
        fail_on=fail_on,
        output_format=output_format,
        input_paths=input_paths,
    )
    for notice in result.notices:
        print(f"notice: {notice}", file=sys.stderr)
    sys.stdout.write(result.output)
    for note in result.deliveries:
        print(note, file=sys.stderr)
    return result.exit_code


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"invalid date {value!r}; use YYYY-MM-DD") from exc
