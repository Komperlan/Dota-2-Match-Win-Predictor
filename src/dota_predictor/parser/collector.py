from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from dota_predictor.parser.checkpoint import CheckpointStore
from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.models import now_utc, unix_seconds_to_utc
from dota_predictor.parser.raw_store import RawPublicMatchStore
from dota_predictor.parser.source import OpenDotaSource, SteamWebApiSource

LOGGER = logging.getLogger(__name__)


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
    fetched = 0
    written = 0
    duplicates = 0
    skipped_by_start_time = 0
    pages = 0
    processed = 0
    stopped_by_start_time = False

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
    raw_store: RawPublicMatchStore,
    checkpoint_store: CheckpointStore,
    config: ParserConfig,
    limit: int | None,
) -> CollectionResult:
    if limit is not None and limit <= 0:
        msg = "limit must be greater than zero"
        raise ValueError(msg)

    checkpoint = checkpoint_store.load()
    start_at_match_id = checkpoint.less_than_match_id if checkpoint else None
    fetched = 0
    written = 0
    duplicates = 0
    skipped_by_start_time = 0
    pages = 0
    processed = 0
    failed = 0
    stopped_by_start_time = False

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
        processed_match_ids: list[int] = []

        for match in batch:
            match_id = int(match["match_id"])
            try:
                payload = source.fetch_match_details(match_id=match_id)
            except httpx.HTTPStatusError as exc:
                if not _should_skip_steam_match_details_error(exc):
                    raise
                failed += 1
                LOGGER.warning(
                    "Skipping Steam match %s after repeated GetMatchDetails status %s",
                    match_id,
                    exc.response.status_code,
                )
                continue
            result = raw_store.save(
                payload,
                source=source.source_name,
                endpoint=source.match_details_endpoint,
                fetched_at=now_utc(),
            )
            fetched += 1
            if result.written:
                written += 1
            else:
                duplicates += 1
            processed += 1
            processed_match_ids.append(match_id)

        page_match_ids = [int(match["match_id"]) for match in sorted_matches]
        if page_match_ids:
            next_start_at_match_id = min(page_match_ids) - 1
            start_at_match_id = next_start_at_match_id if next_start_at_match_id > 0 else None
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


def _should_skip_steam_match_details_error(exc: httpx.HTTPStatusError) -> bool:
    return 500 <= exc.response.status_code <= 599
