"""POST the digest JSON to a generic webhook."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from backup_sentinel import __version__
from backup_sentinel.errors import BackupSentinelError

Opener = Callable[..., Any]


def post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout: float,
    opener: Opener = urllib.request.urlopen,
) -> int:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": f"backup-sentinel/{__version__}",
            **headers,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            return int(response.status)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BackupSentinelError(f"webhook delivery failed: {exc}") from exc
