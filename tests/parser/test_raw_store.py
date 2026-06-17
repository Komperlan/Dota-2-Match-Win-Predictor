from __future__ import annotations

from dota_predictor.parser.raw_store import RawPublicMatchStore

from .conftest import public_match_payload, steam_match_details_payload


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


def test_raw_store_paths_steam_result_payload_by_match_time(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = RawPublicMatchStore(tmp_path / "raw", schema_version=1)

    result = store.save(
        steam_match_details_payload(match_id=222, start_time=1_735_689_600),
        source="steam",
        endpoint="/IDOTA2Match_570/GetMatchDetails/v1/",
    )

    assert result.path.name == "222.json"
    assert result.path.parent.name == "01"
    assert result.path.parent.parent.name == "2025"
