from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.patches import Patch, PatchRegistry
from dota_predictor.parser.raw_store import RawEnvelope


@pytest.fixture
def parser_config(tmp_path: Path) -> ParserConfig:
    return ParserConfig(
        request_delay_seconds=0,
        max_retries=2,
        backoff_initial_seconds=0,
        backoff_max_seconds=0,
        raw_output_dir=tmp_path / "raw",
        normalized_output_dir=tmp_path / "normalized",
        checkpoint_file=tmp_path / "checkpoint.json",
        quality_issues_file=tmp_path / "issues.jsonl",
    )


@pytest.fixture
def patch_registry() -> PatchRegistry:
    return PatchRegistry(
        [
            Patch(
                patch_id="test-patch",
                version="test-patch",
                started_at=datetime(2024, 1, 1, tzinfo=UTC),
                ended_at=datetime(2030, 1, 1, tzinfo=UTC),
                major=True,
            )
        ]
    )


def public_match_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "match_id": 123,
        "match_seq_num": 456,
        "radiant_win": True,
        "start_time": 1_735_689_600,
        "duration": 1800,
        "lobby_type": 7,
        "game_mode": 22,
        "avg_rank_tier": 55,
        "num_rank_tier": 10,
        "cluster": 273,
        "radiant_team": [1, 2, 3, 4, 5],
        "dire_team": [6, 7, 8, 9, 10],
    }
    payload.update(overrides)
    return payload


def raw_envelope(payload: dict[str, Any]) -> RawEnvelope:
    return RawEnvelope(
        source="opendota",
        endpoint="/publicMatches",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        payload=payload,
    )
