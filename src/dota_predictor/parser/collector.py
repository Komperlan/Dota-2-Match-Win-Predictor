from __future__ import annotations

from dataclasses import dataclass

from dota_predictor.parser.checkpoint import CheckpointStore
from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.models import now_utc
from dota_predictor.parser.raw_store import RawPublicMatchStore
from dota_predictor.parser.source import OpenDotaSource


@dataclass(frozen=True)
class CollectionResult:
    fetched: int
    written: int
    duplicates: int
    pages: int
    last_less_than_match_id: int | None

    @property
    def counters(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "written": self.written,
            "duplicates": self.duplicates,
            "pages": self.pages,
        }


def collect_public_matches(
    *,
    source: OpenDotaSource,
    raw_store: RawPublicMatchStore,
    checkpoint_store: CheckpointStore,
    config: ParserConfig,
    limit: int,
) -> CollectionResult:
    if limit <= 0:
        msg = "limit must be greater than zero"
        raise ValueError(msg)

    checkpoint = checkpoint_store.load()
    less_than_match_id = checkpoint.less_than_match_id if checkpoint else None
    fetched = 0
    written = 0
    duplicates = 0
    pages = 0
    processed = 0

    while processed < limit:
        page = source.fetch_public_matches(
            less_than_match_id=less_than_match_id,
            min_rank=config.min_rank,
            max_rank=config.max_rank,
        )
        pages += 1
        if not page:
            break

        sorted_page = sorted(page, key=lambda item: int(item["match_id"]), reverse=True)
        remaining = limit - processed
        batch = sorted_page[:remaining]
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
        if len(batch) < len(sorted_page):
            break

    return CollectionResult(
        fetched=fetched,
        written=written,
        duplicates=duplicates,
        pages=pages,
        last_less_than_match_id=less_than_match_id,
    )
