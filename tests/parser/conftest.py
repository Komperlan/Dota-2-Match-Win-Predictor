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
        steam_raw_output_dir=tmp_path / "steam_raw",
        normalized_output_dir=tmp_path / "normalized",
        steam_normalized_output_dir=tmp_path / "steam_normalized",
        checkpoint_file=tmp_path / "checkpoint.json",
        steam_checkpoint_file=tmp_path / "steam_checkpoint.json",
        quality_issues_file=tmp_path / "issues.jsonl",
        steam_quality_issues_file=tmp_path / "steam_issues.jsonl",
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


def steam_match_history_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "match_id": 123,
        "match_seq_num": 456,
        "start_time": 1_735_689_600,
        "lobby_type": 7,
        "players": [
            {"account_id": 1, "player_slot": 0, "hero_id": 1},
            {"account_id": 2, "player_slot": 1, "hero_id": 2},
            {"account_id": 3, "player_slot": 2, "hero_id": 3},
            {"account_id": 4, "player_slot": 3, "hero_id": 4},
            {"account_id": 5, "player_slot": 4, "hero_id": 5},
            {"account_id": 6, "player_slot": 128, "hero_id": 6},
            {"account_id": 7, "player_slot": 129, "hero_id": 7},
            {"account_id": 8, "player_slot": 130, "hero_id": 8},
            {"account_id": 9, "player_slot": 131, "hero_id": 9},
            {"account_id": 10, "player_slot": 132, "hero_id": 10},
        ],
    }
    payload.update(overrides)
    return payload


def steam_match_details_payload(**overrides: Any) -> dict[str, Any]:
    result = steam_match_history_payload(
        radiant_win=True,
        duration=1800,
        game_mode=22,
        cluster=273,
    )
    result.update(overrides)
    return {"result": result}


def raw_envelope(payload: dict[str, Any]) -> RawEnvelope:
    return RawEnvelope(
        source="opendota",
        endpoint="/publicMatches",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        payload=payload,
    )


def steam_raw_envelope(payload: dict[str, Any]) -> RawEnvelope:
    return RawEnvelope(
        source="steam",
        endpoint="/IDOTA2Match_570/GetMatchDetails/v1/",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=1,
        payload=payload,
    )
