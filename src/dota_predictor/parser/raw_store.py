from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dota_predictor.parser.models import now_utc, unix_seconds_to_utc


@dataclass(frozen=True)
class RawEnvelope:
    source: str
    endpoint: str
    fetched_at: datetime
    schema_version: int
    payload: dict[str, Any]
    path: Path | None = None


@dataclass(frozen=True)
class RawSaveResult:
    path: Path
    written: bool


class RawPublicMatchStore:
    def __init__(self, root: Path, *, schema_version: int) -> None:
        self.root = root
        self.schema_version = schema_version

    def save(
        self,
        payload: dict[str, Any],
        *,
        source: str,
        endpoint: str,
        fetched_at: datetime | None = None,
    ) -> RawSaveResult:
        timestamp = fetched_at or now_utc()
        path = self._path_for_payload(payload, timestamp)
        if path.exists():
            return RawSaveResult(path=path, written=False)

        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "metadata": {
                "source": source,
                "endpoint": endpoint,
                "fetched_at": timestamp.isoformat(),
                "schema_version": self.schema_version,
            },
            "payload": payload,
        }
        path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return RawSaveResult(path=path, written=True)

    def iter_envelopes(self) -> Iterator[RawEnvelope]:
        for path in sorted(self.root.rglob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            metadata = raw.get("metadata", {})
            payload = raw.get("payload", {})
            if not isinstance(payload, dict):
                msg = f"Raw envelope payload must be a mapping: {path}"
                raise ValueError(msg)
            yield RawEnvelope(
                source=str(metadata.get("source", "opendota")),
                endpoint=str(metadata.get("endpoint", "/publicMatches")),
                fetched_at=datetime.fromisoformat(str(metadata["fetched_at"])),
                schema_version=int(metadata.get("schema_version", 1)),
                payload=payload,
                path=path,
            )

    def _path_for_payload(self, payload: dict[str, Any], fallback_timestamp: datetime) -> Path:
        match_payload = _match_payload(payload)
        match_id = int(match_payload["match_id"])
        start_time = match_payload.get("start_time")
        if isinstance(start_time, int):
            match_timestamp = unix_seconds_to_utc(start_time)
        else:
            match_timestamp = fallback_timestamp
        return self.root / f"{match_timestamp:%Y}" / f"{match_timestamp:%m}" / f"{match_id}.json"


def _match_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, dict) and "match_id" in result:
        return result
    return payload
