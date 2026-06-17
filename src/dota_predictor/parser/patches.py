from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

NUMBERED_PATCH_RE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class Patch:
    patch_id: str
    version: str
    started_at: datetime
    ended_at: datetime | None
    major: bool

    def contains(self, value: datetime) -> bool:
        normalized = _ensure_utc(value)
        return self.started_at <= normalized and (
            self.ended_at is None or normalized < self.ended_at
        )


class PatchRegistry:
    def __init__(self, patches: list[Patch]) -> None:
        self._patches = sorted(patches, key=lambda patch: patch.started_at)

    @classmethod
    def from_yaml(cls, path: Path | str = Path("configs/patches.yaml")) -> PatchRegistry:
        patch_path = Path(path)
        loaded = yaml.safe_load(patch_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            msg = f"Patch config must be a mapping: {patch_path}"
            raise ValueError(msg)
        patches = loaded.get("patches", [])
        if not isinstance(patches, list):
            msg = f"Patch config field 'patches' must be a list: {patch_path}"
            raise ValueError(msg)
        return cls([_patch_from_mapping(item) for item in patches])

    def find_patch(self, value: datetime) -> Patch | None:
        for patch in self._patches:
            if patch.contains(value):
                return patch
        return None

    def latest_numbered_patch_family(self) -> str | None:
        numbered_patches = [
            patch for patch in self._patches if NUMBERED_PATCH_RE.fullmatch(patch.patch_id)
        ]
        if not numbered_patches:
            return None
        return max(numbered_patches, key=lambda patch: patch.started_at).patch_id

    def patch_family_start(self, patch_family: str) -> datetime | None:
        family_patches = [
            patch for patch in self._patches if _is_patch_in_family(patch.patch_id, patch_family)
        ]
        if not family_patches:
            return None
        return min(patch.started_at for patch in family_patches)


def _patch_from_mapping(value: Any) -> Patch:
    if not isinstance(value, dict):
        msg = "Each patch entry must be a mapping"
        raise ValueError(msg)
    return Patch(
        patch_id=str(value["patch_id"]),
        version=str(value.get("version", value["patch_id"])),
        started_at=_parse_datetime(value["started_at"]),
        ended_at=_parse_optional_datetime(value.get("ended_at")),
        major=bool(value.get("major", False)),
    )


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value)


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        msg = "Datetime value must be an ISO-8601 string"
        raise ValueError(msg)
    normalized = value.replace("Z", "+00:00")
    return _ensure_utc(datetime.fromisoformat(normalized))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_patch_in_family(patch_id: str, patch_family: str) -> bool:
    if patch_id == patch_family:
        return True
    suffix = patch_id.removeprefix(patch_family)
    return patch_id.startswith(patch_family) and suffix.isalpha()
