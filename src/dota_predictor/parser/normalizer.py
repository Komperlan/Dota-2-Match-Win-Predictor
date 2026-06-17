from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.models import MatchRecord, RawPublicMatch, unix_seconds_to_utc
from dota_predictor.parser.parquet_store import ParquetMatchWriter
from dota_predictor.parser.patches import PatchRegistry
from dota_predictor.parser.quality import QualityIssue, QualityIssueWriter, make_issue
from dota_predictor.parser.raw_store import RawEnvelope, RawPublicMatchStore


@dataclass(frozen=True)
class NormalizationResult:
    raw_seen: int
    normalized: int
    rejected: int
    issues: int


def normalize_public_matches(
    *,
    raw_store: RawPublicMatchStore,
    parquet_writer: ParquetMatchWriter,
    issue_writer: QualityIssueWriter,
    patch_registry: PatchRegistry,
    config: ParserConfig,
) -> NormalizationResult:
    records: list[MatchRecord] = []
    raw_seen = 0
    rejected = 0
    issue_count = 0

    for envelope in raw_store.iter_envelopes():
        raw_seen += 1
        record, issues = normalize_public_match(
            envelope,
            patch_registry=patch_registry,
            config=config,
        )
        issue_writer.write_many(issues)
        issue_count += len(issues)
        if record is None:
            rejected += 1
        else:
            records.append(record)

    normalized = parquet_writer.write(records)
    return NormalizationResult(
        raw_seen=raw_seen,
        normalized=normalized,
        rejected=rejected,
        issues=issue_count,
    )


def normalize_public_match(
    envelope: RawEnvelope,
    *,
    patch_registry: PatchRegistry,
    config: ParserConfig,
) -> tuple[MatchRecord | None, list[QualityIssue]]:
    payload = envelope.payload
    match_id = _extract_match_id(payload)
    try:
        raw = RawPublicMatch.from_payload(payload)
    except (KeyError, TypeError, ValueError) as exc:
        return None, [
            make_issue(
                "schema_error",
                match_id=match_id,
                payload={"error": str(exc), "path": str(envelope.path) if envelope.path else None},
            )
        ]

    issues = _validate_raw_public_match(raw, patch_registry=patch_registry, config=config)
    if issues:
        return None, issues

    start_time = unix_seconds_to_utc(raw.start_time)
    patch = patch_registry.find_patch(start_time)
    if patch is None:
        return None, [
            make_issue(
                "unknown_patch",
                match_id=raw.match_id,
                payload={"start_time": start_time.isoformat()},
            )
        ]

    return (
        MatchRecord(
            match_id=raw.match_id,
            source=envelope.source,
            start_time=start_time,
            patch_id=patch.patch_id,
            radiant_heroes=_team_5(raw.radiant_team),
            dire_heroes=_team_5(raw.dire_team),
            radiant_win=bool(raw.radiant_win),
            avg_rank_tier=raw.avg_rank_tier,
            radiant_avg_mmr=None,
            dire_avg_mmr=None,
            region=raw.cluster,
            game_mode=raw.game_mode,
            lobby_type=raw.lobby_type,
            duration=raw.duration,
            has_leaver=None,
            collected_at=envelope.fetched_at,
            schema_version=config.schema_version,
        ),
        [],
    )


def _validate_raw_public_match(
    raw: RawPublicMatch,
    *,
    patch_registry: PatchRegistry,
    config: ParserConfig,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    all_heroes = (*raw.radiant_team, *raw.dire_team)

    if len(raw.radiant_team) != 5 or len(raw.dire_team) != 5:
        issues.append(
            make_issue(
                "invalid_team_size",
                match_id=raw.match_id,
                payload={
                    "radiant_count": len(raw.radiant_team),
                    "dire_count": len(raw.dire_team),
                },
            )
        )

    if any(hero_id == 0 for hero_id in all_heroes):
        issues.append(make_issue("zero_hero_id", match_id=raw.match_id, payload={}))

    if len(set(all_heroes)) != len(all_heroes):
        issues.append(
            make_issue(
                "duplicate_hero_id",
                match_id=raw.match_id,
                payload={"heroes": list(all_heroes)},
            )
        )

    if raw.radiant_win is None:
        issues.append(make_issue("missing_radiant_win", match_id=raw.match_id, payload={}))

    if raw.game_mode not in config.allowed_game_modes:
        issues.append(
            make_issue(
                "unsupported_game_mode",
                match_id=raw.match_id,
                payload={"game_mode": raw.game_mode},
            )
        )

    if raw.lobby_type not in config.allowed_lobby_types:
        issues.append(
            make_issue(
                "unsupported_lobby_type",
                match_id=raw.match_id,
                payload={"lobby_type": raw.lobby_type},
            )
        )

    if raw.duration is None or raw.duration < config.min_duration_seconds:
        issues.append(
            make_issue(
                "match_too_short",
                match_id=raw.match_id,
                payload={"duration": raw.duration},
            )
        )

    start_time = unix_seconds_to_utc(raw.start_time)
    if patch_registry.find_patch(start_time) is None:
        issues.append(
            make_issue(
                "unknown_patch",
                match_id=raw.match_id,
                payload={"start_time": start_time.isoformat()},
            )
        )

    return issues


def _extract_match_id(payload: dict[str, Any]) -> int | None:
    try:
        value = payload.get("match_id")
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _team_5(value: tuple[int, ...]) -> tuple[int, int, int, int, int]:
    if len(value) != 5:
        msg = "Expected a five-hero team"
        raise ValueError(msg)
    return (value[0], value[1], value[2], value[3], value[4])
