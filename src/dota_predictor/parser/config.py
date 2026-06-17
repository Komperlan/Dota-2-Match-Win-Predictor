from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ParserConfig:
    source_base_url: str = "https://api.opendota.com/api"
    public_matches_endpoint: str = "/publicMatches"
    steam_base_url: str = "https://api.steampowered.com"
    steam_match_history_endpoint: str = "/IDOTA2Match_570/GetMatchHistory/v1/"
    steam_match_details_endpoint: str = "/IDOTA2Match_570/GetMatchDetails/v1/"
    steam_matches_requested: int = 100
    steam_history_game_mode: int | None = 22
    steam_history_min_players: int | None = 10
    request_delay_seconds: float = 1.0
    max_retries: int = 5
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    timeout_seconds: float = 20.0
    min_rank: int | None = None
    max_rank: int | None = None
    collection_min_start_time: datetime | None = None
    allowed_game_modes: tuple[int, ...] = (22,)
    allowed_lobby_types: tuple[int, ...] = (7,)
    min_duration_seconds: int = 600
    raw_output_dir: Path = Path("data/raw/opendota/public_matches")
    steam_raw_output_dir: Path = Path("data/raw/steam/match_details")
    normalized_output_dir: Path = Path("data/normalized/matches")
    steam_normalized_output_dir: Path = Path("data/normalized/steam_matches")
    checkpoint_file: Path = Path("artifacts/checkpoints/opendota_public.json")
    steam_checkpoint_file: Path = Path("artifacts/checkpoints/steam_match_history.json")
    quality_issues_file: Path = Path("artifacts/quality/public_matches_issues.jsonl")
    steam_quality_issues_file: Path = Path("artifacts/quality/steam_match_details_issues.jsonl")
    schema_version: int = 1

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> ParserConfig:
        return cls(
            source_base_url=str(values.get("source_base_url", cls.source_base_url)),
            public_matches_endpoint=str(
                values.get("public_matches_endpoint", cls.public_matches_endpoint)
            ),
            steam_base_url=str(values.get("steam_base_url", cls.steam_base_url)),
            steam_match_history_endpoint=str(
                values.get("steam_match_history_endpoint", cls.steam_match_history_endpoint)
            ),
            steam_match_details_endpoint=str(
                values.get("steam_match_details_endpoint", cls.steam_match_details_endpoint)
            ),
            steam_matches_requested=int(
                values.get("steam_matches_requested", cls.steam_matches_requested)
            ),
            steam_history_game_mode=_optional_int(
                values.get("steam_history_game_mode", cls.steam_history_game_mode)
            ),
            steam_history_min_players=_optional_int(
                values.get("steam_history_min_players", cls.steam_history_min_players)
            ),
            request_delay_seconds=float(
                values.get("request_delay_seconds", cls.request_delay_seconds)
            ),
            max_retries=int(values.get("max_retries", cls.max_retries)),
            backoff_initial_seconds=float(
                values.get("backoff_initial_seconds", cls.backoff_initial_seconds)
            ),
            backoff_max_seconds=float(values.get("backoff_max_seconds", cls.backoff_max_seconds)),
            timeout_seconds=float(values.get("timeout_seconds", cls.timeout_seconds)),
            min_rank=_optional_int(values.get("min_rank")),
            max_rank=_optional_int(values.get("max_rank")),
            collection_min_start_time=_optional_datetime(
                values.get("collection_min_start_time")
            ),
            allowed_game_modes=tuple(
                int(value) for value in values.get("allowed_game_modes", cls.allowed_game_modes)
            ),
            allowed_lobby_types=tuple(
                int(value) for value in values.get("allowed_lobby_types", cls.allowed_lobby_types)
            ),
            min_duration_seconds=int(
                values.get("min_duration_seconds", cls.min_duration_seconds)
            ),
            raw_output_dir=Path(values.get("raw_output_dir", cls.raw_output_dir)),
            steam_raw_output_dir=Path(
                values.get("steam_raw_output_dir", cls.steam_raw_output_dir)
            ),
            normalized_output_dir=Path(
                values.get("normalized_output_dir", cls.normalized_output_dir)
            ),
            steam_normalized_output_dir=Path(
                values.get("steam_normalized_output_dir", cls.steam_normalized_output_dir)
            ),
            checkpoint_file=Path(values.get("checkpoint_file", cls.checkpoint_file)),
            steam_checkpoint_file=Path(
                values.get("steam_checkpoint_file", cls.steam_checkpoint_file)
            ),
            quality_issues_file=Path(
                values.get("quality_issues_file", cls.quality_issues_file)
            ),
            steam_quality_issues_file=Path(
                values.get("steam_quality_issues_file", cls.steam_quality_issues_file)
            ),
            schema_version=int(values.get("schema_version", cls.schema_version)),
        )


def load_parser_config(path: Path | str = Path("configs/parser.yaml")) -> ParserConfig:
    config_path = Path(path)
    if not config_path.exists():
        return ParserConfig()
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        msg = f"Parser config must be a mapping: {config_path}"
        raise ValueError(msg)
    return ParserConfig.from_mapping(loaded)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        return int(value)
    msg = f"Expected int-compatible value, got {type(value).__name__}"
    raise ValueError(msg)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"Expected ISO datetime string or null, got {type(value).__name__}"
        raise ValueError(msg)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
