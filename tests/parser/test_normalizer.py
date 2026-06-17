from __future__ import annotations

import json

from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.normalizer import (
    normalize_public_match,
    normalize_public_matches,
    normalize_steam_match_details,
)
from dota_predictor.parser.parquet_store import ParquetMatchWriter
from dota_predictor.parser.patches import PatchRegistry
from dota_predictor.parser.quality import QualityIssueWriter
from dota_predictor.parser.raw_store import RawPublicMatchStore

from .conftest import (
    public_match_payload,
    raw_envelope,
    steam_match_details_payload,
    steam_raw_envelope,
)


def test_valid_public_match_normalizes_to_match_record(
    parser_config: ParserConfig,
    patch_registry: PatchRegistry,
) -> None:
    record, issues = normalize_public_match(
        raw_envelope(public_match_payload()),
        patch_registry=patch_registry,
        config=parser_config,
    )

    assert issues == []
    assert record is not None
    assert record.match_id == 123
    assert record.patch_id == "test-patch"
    assert record.radiant_heroes == (1, 2, 3, 4, 5)
    assert record.dire_heroes == (6, 7, 8, 9, 10)
    assert record.radiant_avg_mmr is None
    assert record.dire_avg_mmr is None
    assert record.has_leaver is None
    assert record.region == 273


def test_invalid_team_size_is_rejected(
    parser_config: ParserConfig,
    patch_registry: PatchRegistry,
) -> None:
    record, issues = normalize_public_match(
        raw_envelope(public_match_payload(radiant_team=[1, 2, 3])),
        patch_registry=patch_registry,
        config=parser_config,
    )

    assert record is None
    assert {issue.issue_type for issue in issues} >= {"invalid_team_size"}


def test_duplicate_hero_id_is_rejected(
    parser_config: ParserConfig,
    patch_registry: PatchRegistry,
) -> None:
    record, issues = normalize_public_match(
        raw_envelope(public_match_payload(dire_team=[5, 6, 7, 8, 9])),
        patch_registry=patch_registry,
        config=parser_config,
    )

    assert record is None
    assert {issue.issue_type for issue in issues} >= {"duplicate_hero_id"}


def test_zero_hero_id_is_rejected(
    parser_config: ParserConfig,
    patch_registry: PatchRegistry,
) -> None:
    record, issues = normalize_public_match(
        raw_envelope(public_match_payload(dire_team=[0, 6, 7, 8, 9])),
        patch_registry=patch_registry,
        config=parser_config,
    )

    assert record is None
    assert {issue.issue_type for issue in issues} >= {"zero_hero_id"}


def test_unsupported_game_mode_and_lobby_type_are_rejected(
    parser_config: ParserConfig,
    patch_registry: PatchRegistry,
) -> None:
    record, issues = normalize_public_match(
        raw_envelope(public_match_payload(game_mode=23, lobby_type=0)),
        patch_registry=patch_registry,
        config=parser_config,
    )

    assert record is None
    assert {issue.issue_type for issue in issues} >= {
        "unsupported_game_mode",
        "unsupported_lobby_type",
    }


def test_unknown_patch_writes_quality_issue(
    parser_config: ParserConfig,
) -> None:
    registry = PatchRegistry([])
    record, issues = normalize_public_match(
        raw_envelope(public_match_payload()),
        patch_registry=registry,
        config=parser_config,
    )

    assert record is None
    assert {issue.issue_type for issue in issues} >= {"unknown_patch"}


def test_normalization_writes_quality_issue_jsonl(
    parser_config: ParserConfig,
) -> None:
    raw_store = RawPublicMatchStore(parser_config.raw_output_dir, schema_version=1)
    raw_store.save(
        public_match_payload(match_id=789),
        source="opendota",
        endpoint="/publicMatches",
    )
    issue_writer = QualityIssueWriter(parser_config.quality_issues_file, reset=True)

    result = normalize_public_matches(
        raw_store=raw_store,
        parquet_writer=ParquetMatchWriter(parser_config.normalized_output_dir),
        issue_writer=issue_writer,
        patch_registry=PatchRegistry([]),
        config=parser_config,
    )

    lines = parser_config.quality_issues_file.read_text(encoding="utf-8").splitlines()
    assert result.rejected == 1
    assert len(lines) == 1
    assert json.loads(lines[0])["issue_type"] == "unknown_patch"


def test_valid_steam_match_details_normalizes_to_match_record(
    parser_config: ParserConfig,
    patch_registry: PatchRegistry,
) -> None:
    payload = steam_match_details_payload(
        result_extra="ignored",
        players=[
            {"account_id": 1, "player_slot": 2, "hero_id": 3, "leaver_status": 0},
            {"account_id": 2, "player_slot": 0, "hero_id": 1, "leaver_status": 0},
            {"account_id": 3, "player_slot": 4, "hero_id": 5, "leaver_status": 0},
            {"account_id": 4, "player_slot": 1, "hero_id": 2, "leaver_status": 0},
            {"account_id": 5, "player_slot": 3, "hero_id": 4, "leaver_status": 0},
            {"account_id": 6, "player_slot": 132, "hero_id": 10, "leaver_status": 0},
            {"account_id": 7, "player_slot": 128, "hero_id": 6, "leaver_status": 0},
            {"account_id": 8, "player_slot": 131, "hero_id": 9, "leaver_status": 0},
            {"account_id": 9, "player_slot": 129, "hero_id": 7, "leaver_status": 0},
            {"account_id": 10, "player_slot": 130, "hero_id": 8, "leaver_status": 3},
        ],
    )

    record, issues = normalize_steam_match_details(
        steam_raw_envelope(payload),
        patch_registry=patch_registry,
        config=parser_config,
    )

    assert issues == []
    assert record is not None
    assert record.source == "steam"
    assert record.radiant_heroes == (1, 2, 3, 4, 5)
    assert record.dire_heroes == (6, 7, 8, 9, 10)
    assert record.radiant_win is True
    assert record.avg_rank_tier is None
    assert record.has_leaver is True
