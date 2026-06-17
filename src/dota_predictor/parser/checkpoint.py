from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dota_predictor.parser.models import now_utc


@dataclass(frozen=True)
class PublicMatchesCheckpoint:
    less_than_match_id: int | None
    counters: dict[str, int]
    updated_at: datetime


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> PublicMatchesCheckpoint | None:
        if not self.path.exists():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return PublicMatchesCheckpoint(
            less_than_match_id=_optional_int(raw.get("less_than_match_id")),
            counters={str(key): int(value) for key, value in raw.get("counters", {}).items()},
            updated_at=datetime.fromisoformat(str(raw["updated_at"])),
        )

    def save(self, *, less_than_match_id: int | None, counters: dict[str, int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "less_than_match_id": less_than_match_id,
            "counters": counters,
            "updated_at": now_utc().isoformat(),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        return int(value)
    msg = f"Expected int-compatible value, got {type(value).__name__}"
    raise ValueError(msg)
