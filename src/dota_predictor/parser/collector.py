from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dota_predictor.parser.checkpoint import CheckpointStore
from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.models import now_utc, unix_seconds_to_utc
from dota_predictor.parser.raw_store import RawPublicMatchStore
from dota_predictor.parser.source import OpenDotaSource


@dataclass(frozen=True)
class CollectionResult:
    fetched: int
    written: int
    duplicates: int
    skipped_by_start_time: int
    pages: int
    last_less_than_match_id: int | None
    stopped_by_start_time: bool

    @property
    def counters(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "written": self.written,
            "duplicates": self.duplicates,
            "skipped_by_start_time": self.skipped_by_start_time,
            "pages": self.pages,
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
