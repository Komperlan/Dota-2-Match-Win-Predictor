from __future__ import annotations

from dota_predictor.parser.raw_store import RawPublicMatchStore

from .conftest import public_match_payload


def test_raw_store_is_immutable_for_existing_match(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = RawPublicMatchStore(tmp_path / "raw", schema_version=1)
    payload = public_match_payload(match_id=111, avg_rank_tier=10)

    first = store.save(payload, source="opendota", endpoint="/publicMatches")
    second = store.save(
        public_match_payload(match_id=111, avg_rank_tier=90),
        source="opendota",
        endpoint="/publicMatches",
    )

    saved = first.path.read_text(encoding="utf-8")
    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert '"avg_rank_tier": 10' in saved
    assert '"avg_rank_tier": 90' not in saved
