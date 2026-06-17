from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

import httpx

from dota_predictor.parser.checkpoint import CheckpointStore
from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.models import now_utc, unix_seconds_to_utc
from dota_predictor.parser.raw_store import RawPublicMatchStore
from dota_predictor.parser.source import OpenDotaSource, SteamWebApiSource

LOGGER = logging.getLogger(__name__)

type MatchDetailsFetch = tuple[dict[str, Any], str, str]
type MatchDetailsSource = Literal["steam_sequence", "steam_details"]


@dataclass(frozen=True)
class CollectionResult:
    fetched: int
    written: int
    duplicates: int
    skipped_by_start_time: int
    pages: int
    last_less_than_match_id: int | None
    stopped_by_start_time: bool
    failed: int = 0

    @property
    def counters(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "written": self.written,
            "duplicates": self.duplicates,
            "skipped_by_start_time": self.skipped_by_start_time,
            "pages": self.pages,
            "failed": self.failed,
        }


def collect_public_matches(
    *,
    source: OpenDotaSource,
    raw_store: RawPublicMatchStore,
    checkpoint_store: CheckpointStore,
    config: ParserConfig,
    limit: int | None,
) -> CollectionResult:
    if limit is not None and limit <= 0:
        msg = "limit must be greater than zero"
        raise ValueError(msg)

    checkpoint = checkpoint_store.load()
    less_than_match_id = checkpoint.less_than_match_id if checkpoint else None
    if checkpoint is None and _has_existing_raw_files(raw_store):
        LOGGER.warning(
            "No OpenDota checkpoint found, but raw_dir=%s already has files; "
            "duplicates are expected until a new checkpoint is saved",
            raw_store.root,
        )
    fetched = 0
    written = 0
    duplicates = 0
    skipped_by_start_time = 0
    pages = 0
    processed = 0
    stopped_by_start_time = False

    LOGGER.info(
        "Starting OpenDota collection limit=%s resume_less_than_match_id=%s cutoff=%s raw_dir=%s",
        limit if limit is not None else "all",
        less_than_match_id,
        config.collection_min_start_time.isoformat()
        if config.collection_min_start_time is not None
        else None,
        raw_store.root,
    )
    while limit is None or processed < limit:
        page = source.fetch_public_matches(
            less_than_match_id=less_than_match_id,
            min_rank=config.min_rank,
            max_rank=config.max_rank,
        )
        pages += 1
        if not page:
            break

        sorted_page = sorted(page, key=lambda item: int(item["match_id"]), reverse=True)
        remaining = None if limit is None else limit - processed
        selected_page, reached_start_time = _filter_by_min_start_time(
            sorted_page,
            config.collection_min_start_time,
        )
        if reached_start_time:
            stopped_by_start_time = True
            skipped_by_start_time += len(sorted_page) - len(selected_page)
        batch = selected_page if remaining is None else selected_page[:remaining]
        LOGGER.info(
            "OpenDota page=%s received=%s selected=%s batch=%s less_than_match_id=%s",
            pages,
            len(sorted_page),
            len(selected_page),
            len(batch),
            less_than_match_id,
        )
        fetched += len(batch)
        fetched_at = now_utc()

        processed_match_ids: list[int] = []
        for payload in batch:
            result = raw_store.save(
                payload,
                source=source.source_name,
                endpoint=source.endpoint,
                fetched_at=fetched_at,
            )
            if result.written:
                written += 1
            else:
                duplicates += 1
            processed_match_ids.append(int(payload["match_id"]))

        processed += len(batch)
        if not processed_match_ids:
            break
        if processed_match_ids:
            less_than_match_id = min(processed_match_ids)
            checkpoint_store.save(
                less_than_match_id=less_than_match_id,
                counters={
                    "fetched": fetched,
                    "written": written,
                    "duplicates": duplicates,
                    "pages": pages,
                },
            )
            LOGGER.info(
                "OpenDota checkpoint page=%s next_less_than_match_id=%s fetched=%s "
                "raw_written=%s raw_duplicates=%s skipped_by_start_time=%s",
                pages,
                less_than_match_id,
                fetched,
                written,
                duplicates,
                skipped_by_start_time,
            )
        if limit is not None and len(batch) < len(sorted_page):
            break
        if stopped_by_start_time:
            break

    return CollectionResult(
        fetched=fetched,
        written=written,
        duplicates=duplicates,
        skipped_by_start_time=skipped_by_start_time,
        pages=pages,
        last_less_than_match_id=less_than_match_id,
        stopped_by_start_time=stopped_by_start_time,
    )


def collect_steam_matches(
    *,
    source: SteamWebApiSource,
    details_source: str | None = None,
    raw_store: RawPublicMatchStore,
    checkpoint_store: CheckpointStore,
    config: ParserConfig,
    limit: int | None,
) -> CollectionResult:
    if limit is not None and limit <= 0:
        msg = "limit must be greater than zero"
        raise ValueError(msg)
    normalized_details_source = _normalize_match_details_source(
        details_source or config.steam_details_source
    )

    checkpoint = checkpoint_store.load()
    start_at_match_id = checkpoint.less_than_match_id if checkpoint else None
    if checkpoint is None and _has_existing_raw_files(raw_store):
        LOGGER.warning(
            "No Steam checkpoint found, but raw_dir=%s already has files; "
            "raw duplicates are expected until a new checkpoint is saved",
            raw_store.root,
        )
    fetched = 0
    written = 0
    duplicates = 0
    skipped_by_start_time = 0
    pages = 0
    processed = 0
    failed = 0
    stopped_by_start_time = False

    LOGGER.info(
        "Starting Steam collection limit=%s details_source=%s resume_start_at_match_id=%s "
        "cutoff=%s raw_dir=%s",
        limit if limit is not None else "all",
        normalized_details_source,
        start_at_match_id,
        config.collection_min_start_time.isoformat()
        if config.collection_min_start_time is not None
        else None,
        raw_store.root,
    )
    while limit is None or processed < limit:
        history = source.fetch_match_history(start_at_match_id=start_at_match_id)
        pages += 1
        matches = history.get("matches", [])
        if not isinstance(matches, list):
            msg = "Steam GetMatchHistory result.matches must be a list"
            raise ValueError(msg)
        if not matches:
            break

        sorted_matches = sorted(matches, key=lambda item: int(item["match_id"]), reverse=True)
        selected_matches, reached_start_time = _filter_by_min_start_time(
            sorted_matches,
            config.collection_min_start_time,
        )
        if reached_start_time:
            stopped_by_start_time = True
            skipped_by_start_time += len(sorted_matches) - len(selected_matches)

        remaining = None if limit is None else limit - processed
        batch = selected_matches if remaining is None else selected_matches[:remaining]
        LOGGER.info(
            "Steam history page=%s received=%s selected=%s batch=%s "
            "results_remaining=%s start_at_match_id=%s",
            pages,
            len(sorted_matches),
            len(selected_matches),
            len(batch),
            history.get("results_remaining"),
            start_at_match_id,
        )
        processed_match_ids: list[int] = []

        for index, match in enumerate(batch, start=1):
            match_id = int(match["match_id"])
            LOGGER.debug(
                "Fetching details match_id=%s page=%s index=%s/%s details_source=%s",
                match_id,
                pages,
                index,
                len(batch),
                normalized_details_source,
            )
            details = _fetch_steam_match_details(
                source=source,
                details_source=normalized_details_source,
                match=match,
            )
            processed += 1
            if details is None:
                failed += 1
                start_at_match_id = _next_steam_start_at_match_id(match_id)
                checkpoint_store.save(
                    less_than_match_id=start_at_match_id,
                    counters={
                        "fetched": fetched,
                        "written": written,
                        "duplicates": duplicates,
                        "failed": failed,
                        "skipped_by_start_time": skipped_by_start_time,
                        "pages": pages,
                    },
                )
                continue
            payload, payload_source, endpoint = details
            result = raw_store.save(
                payload,
                source=payload_source,
                endpoint=endpoint,
                fetched_at=now_utc(),
            )
            fetched += 1
            if result.written:
                written += 1
            else:
                duplicates += 1
            processed_match_ids.append(match_id)
            start_at_match_id = _next_steam_start_at_match_id(match_id)
            checkpoint_store.save(
                less_than_match_id=start_at_match_id,
                counters={
                    "fetched": fetched,
                    "written": written,
                    "duplicates": duplicates,
                    "failed": failed,
                    "skipped_by_start_time": skipped_by_start_time,
                    "pages": pages,
                },
            )
            if index == len(batch) or index % 10 == 0:
                LOGGER.info(
                    "Steam details progress page=%s index=%s/%s total_processed=%s "
                    "details_ok=%s raw_written=%s raw_duplicates=%s details_failed=%s "
                    "last_match_id=%s",
                    pages,
                    index,
                    len(batch),
                    processed,
                    fetched,
                    written,
                    duplicates,
                    failed,
                    match_id,
                )

        if batch:
            LOGGER.info(
                "Steam checkpoint page=%s next_start_at_match_id=%s details_ok=%s "
                "raw_written=%s raw_duplicates=%s details_failed=%s skipped_by_start_time=%s",
                pages,
                start_at_match_id,
                fetched,
                written,
                duplicates,
                failed,
                skipped_by_start_time,
            )

        if not processed_match_ids and stopped_by_start_time:
            break
        if limit is not None and len(batch) < len(selected_matches):
            break
        if stopped_by_start_time:
            break
        if int(history.get("results_remaining", 0)) <= 0:
            break

    return CollectionResult(
        fetched=fetched,
        written=written,
        duplicates=duplicates,
        skipped_by_start_time=skipped_by_start_time,
        pages=pages,
        last_less_than_match_id=start_at_match_id,
        stopped_by_start_time=stopped_by_start_time,
        failed=failed,
    )


def _filter_by_min_start_time(
    page: list[dict[str, Any]],
    min_start_time: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    if min_start_time is None:
        return page, False

    selected: list[dict[str, Any]] = []
    reached_min_start_time = False
    for payload in page:
        start_time = unix_seconds_to_utc(int(payload["start_time"]))
        if start_time < min_start_time:
            reached_min_start_time = True
            continue
        selected.append(payload)
    return selected, reached_min_start_time


def _next_steam_start_at_match_id(match_id: int) -> int | None:
    candidate = match_id - 1
    return candidate if candidate > 0 else None


def _has_existing_raw_files(raw_store: RawPublicMatchStore) -> bool:
    return raw_store.root.exists() and next(raw_store.root.rglob("*.json"), None) is not None


def _should_skip_steam_match_details_error(exc: httpx.HTTPStatusError) -> bool:
    return 500 <= exc.response.status_code <= 599


def _normalize_match_details_source(value: str) -> MatchDetailsSource:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "steam": "steam_details",
        "steam_details": "steam_details",
        "steam_sequence": "steam_sequence",
        "sequence": "steam_sequence",
    }
    if normalized in aliases:
        return cast(MatchDetailsSource, aliases[normalized])
    msg = "steam_details_source must be one of: steam_sequence, steam_details"
    raise ValueError(msg)


def _fetch_steam_match_details(
    *,
    source: SteamWebApiSource,
    details_source: MatchDetailsSource,
    match: dict[str, Any],
) -> MatchDetailsFetch | None:
    match_id = int(match["match_id"])
    if details_source == "steam_sequence":
        return _fetch_steam_sequence_match_details(source, match=match)

    try:
        return (
            source.fetch_match_details(match_id=match_id),
            source.source_name,
            source.match_details_endpoint,
        )
    except httpx.HTTPStatusError as exc:
        if not _should_skip_steam_match_details_error(exc):
            raise
        LOGGER.warning(
            "Skipping Steam match %s after GetMatchDetails status %s",
            match_id,
            exc.response.status_code,
        )
        return None


def _fetch_steam_sequence_match_details(
    source: SteamWebApiSource,
    *,
    match: dict[str, Any],
) -> MatchDetailsFetch | None:
    match_id = int(match["match_id"])
    match_seq_num = match.get("match_seq_num")
    if match_seq_num is None:
        LOGGER.warning("Skipping Steam match %s because match_seq_num is missing", match_id)
        return None

    try:
        history = source.fetch_match_history_by_sequence(
            start_at_match_seq_num=int(match_seq_num),
            matches_requested=1,
        )
    except httpx.HTTPStatusError as exc:
        if not _should_skip_steam_match_details_error(exc):
            raise
        LOGGER.warning(
            "Skipping Steam match %s after GetMatchHistoryBySequenceNum status %s",
            match_id,
            exc.response.status_code,
        )
        return None

    matches = history.get("matches", [])
    if not isinstance(matches, list):
        msg = "Steam GetMatchHistoryBySequenceNum result.matches must be a list"
        raise ValueError(msg)
    payload = _find_sequence_match(matches, match_id=match_id)
    if payload is None:
        LOGGER.warning(
            "Skipping Steam match %s because sequence response did not include it",
            match_id,
        )
        return None
    if not _has_match_players(payload):
        LOGGER.warning(
            "Skipping Steam match %s because sequence details contain no players",
            match_id,
        )
        return None
    return (
        payload,
        source.source_name,
        source.match_history_by_sequence_endpoint,
    )


def _find_sequence_match(matches: list[object], *, match_id: int) -> dict[str, Any] | None:
    for item in matches:
        if not isinstance(item, dict):
            continue
        try:
            if int(item["match_id"]) == match_id:
                return item
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _has_match_players(payload: dict[str, Any]) -> bool:
    result = payload.get("result")
    match_payload = result if isinstance(result, dict) else payload
    return isinstance(match_payload.get("players"), list)
