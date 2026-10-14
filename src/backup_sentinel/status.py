"""Map vendor status words onto critical, warning, and ok."""

from __future__ import annotations

import re

from backup_sentinel.errors import ParseError
from backup_sentinel.models import Severity

_CRITICAL = re.compile(r"fail|error|fatal|abort|cancel|timed out|timeout", re.IGNORECASE)
_WARNING = re.compile(r"warn|partial", re.IGNORECASE)
_OK = re.compile(r"success|succeed|complet|finish|\bok\b|healthy", re.IGNORECASE)


def classify_status(raw: str) -> Severity:
    """Classify a vendor status phrase.

    Failure words win over success words, so "completed with errors" is
    critical. Warning words win over plain success, so "success with warnings"
    stays a warning. An unrecognized phrase is a warning: a new wording should
    show up in the digest instead of being treated as healthy.
    """
    value = " ".join(raw.split())
    if not value:
        raise ParseError("missing status")
    if _CRITICAL.search(value):
        return Severity.CRITICAL
    if _WARNING.search(value):
        return Severity.WARNING
    if _OK.search(value):
        return Severity.OK
    return Severity.WARNING
