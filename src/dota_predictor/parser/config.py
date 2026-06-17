from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ParserConfig:
    source_base_url: str = "https://api.opendota.com/api"
    public_matches_endpoint: str = "/publicMatches"
    request_delay_seconds: float = 1.0
    max_retries: int = 5
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    timeout_seconds: float = 20.0
    min_rank: int | None = None
    max_rank: int | None = None
    allowed_game_modes: tuple[int, ...] = (22,)
    allowed_lobby_types: tuple[int, ...] = (7,)
    min_duration_seconds: int = 600
    raw_output_dir: Path = Path("data/raw/opendota/public_matches")
    normalized_output_dir: Path = Path("data/normalized/matches")
    checkpoint_file: Path = Path("artifacts/checkpoints/opendota_public.json")
    quality_issues_file: Path = Path("artifacts/quality/public_matches_issues.jsonl")
    schema_version: int = 1

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> ParserConfig:
        return cls(
            source_base_url=str(values.get("source_base_url", cls.source_base_url)),
            public_matches_endpoint=str(
                values.get("public_matches_endpoint", cls.public_matches_endpoint)
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
            normalized_output_dir=Path(
                values.get("normalized_output_dir", cls.normalized_output_dir)
            ),
            checkpoint_file=Path(values.get("checkpoint_file", cls.checkpoint_file)),
            quality_issues_file=Path(
                values.get("quality_issues_file", cls.quality_issues_file)
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
