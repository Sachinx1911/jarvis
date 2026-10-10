"""Append-only JSONL audit log. Secrets are redacted before anything is written."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Key names that hold secrets. "input_tokens" etc. are counts, not secrets.
_SECRET_KEY = re.compile(r"(api[_-]?key|(^|_)token$|secret|password|authorization)", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"(sk-ant-[A-Za-z0-9_\-]+|tvly-[A-Za-z0-9_\-]+)")
REDACTED = "[REDACTED]"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if _SECRET_KEY.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    return value


class AuditLog:
    def __init__(self, path: Path):
        self.path = path

    def write(self, event: str, **fields: Any) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event}
        record.update(redact(fields))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if new and sys.platform != "win32":
            os.chmod(self.path, 0o600)
