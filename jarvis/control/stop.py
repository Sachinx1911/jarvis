"""Emergency stop: a STOP file in the data folder halts every provider and tool call."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class EmergencyStop(Exception):
    pass


class StopSwitch:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "STOP"

    def engaged(self) -> bool:
        return self.path.exists()

    def engage(self, reason: str = "") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"{datetime.now().isoformat()} {reason}\n", encoding="utf-8")

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def check(self) -> None:
        if self.engaged():
            raise EmergencyStop("emergency stop is on (run: jarvis resume)")
