from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import httpx

from dota_predictor.parser.checkpoint import CheckpointStore
from dota_predictor.parser.collector import collect_public_matches, collect_steam_matches
from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.raw_store import RawPublicMatchStore
from dota_predictor.parser.source import OpenDotaSource, SteamWebApiSource

from .conftest import public_match_payload, steam_match_details_payload, steam_match_history_payload


def test_collect_single_page(parser_config: ParserConfig) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                public_match_payload(match_id=200),
                public_match_payload(match_id=199),
            ],
        )
    )
    client = httpx.Client(transport=transport, base_url=parser_config.source_base_url)
    source = OpenDotaSource(parser_config, client=client, sleep=lambda _: None)
    raw_store = RawPublicMatchStore(parser_config.raw_output_dir, schema_version=1)
    checkpoint_store = CheckpointStore(parser_config.checkpoint_file)

    result = collect_public_matches(
        source=source,
        raw_store=raw_store,
        checkpoint_store=checkpoint_store,
        config=parser_config,
        limit=2,
    )

    assert result.fetched == 2
    assert result.written == 2
    assert result.last_less_than_match_id == 199
    assert len(list(parser_config.raw_output_dir.rglob("*.json"))) == 2


def test_collect_resumes_from_checkpoint(parser_config: ParserConfig) -> None:
    seen_less_than: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_less_than.append(request.url.params.get("less_than_match_id"))
        return httpx.Response(200, json=[public_match_payload(match_id=100)])

    checkpoint_store = CheckpointStore(parser_config.checkpoint_file)
    checkpoint_store.save(less_than_match_id=101, counters={})
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=parser_config.source_base_url,
    )
    source = OpenDotaSource(parser_config, client=client, sleep=lambda _: None)

    collect_public_matches(
        source=source,
        raw_store=RawPublicMatchStore(parser_config.raw_output_dir, schema_version=1),
        checkpoint_store=checkpoint_store,
        config=parser_config,
        limit=1,
    )

    assert seen_less_than == ["101"]


def test_collect_all_stops_on_empty_page(parser_config: ParserConfig) -> None:
    pages = [
        [public_match_payload(match_id=300), public_match_payload(match_id=299)],
        [public_match_payload(match_id=298)],
        [],
    ]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        page = pages[calls]
        calls += 1
        return httpx.Response(200, json=page)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=parser_config.source_base_url,
    )
    source = OpenDotaSource(parser_config, client=client, sleep=lambda _: None)

    result = collect_public_matches(
        source=source,
        raw_store=RawPublicMatchStore(parser_config.raw_output_dir, schema_version=1),
        checkpoint_store=CheckpointStore(parser_config.checkpoint_file),
        config=parser_config,
        limit=None,
    )

    assert result.fetched == 3
    assert result.written == 3
    assert result.pages == 3
    assert result.last_less_than_match_id == 298


def test_collect_stops_at_collection_min_start_time(parser_config: ParserConfig) -> None:
    config = replace(
        parser_config,
        collection_min_start_time=datetime(2025, 1, 1, tzinfo=UTC),
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json=[
                public_match_payload(match_id=400, start_time=1_735_689_600),
                public_match_payload(match_id=399, start_time=1_704_067_200),
            ],
        )
    )
    client = httpx.Client(transport=transport, base_url=config.source_base_url)
    source = OpenDotaSource(config, client=client, sleep=lambda _: None)

    result = collect_public_matches(
        source=source,
        raw_store=RawPublicMatchStore(config.raw_output_dir, schema_version=1),
        checkpoint_store=CheckpointStore(config.checkpoint_file),
        config=config,
        limit=None,
    )

    assert result.fetched == 1
    assert result.written == 1
    assert result.skipped_by_start_time == 1
    assert result.stopped_by_start_time is True
    assert len(list(config.raw_output_dir.rglob("*.json"))) == 1


def test_retry_after_429(parser_config: ParserConfig) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "limit"})
        return httpx.Response(200, json=[public_match_payload(match_id=300)])

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=parser_config.source_base_url,
    )
    source = OpenDotaSource(parser_config, client=client, sleep=sleeps.append)

    page = source.fetch_public_matches()

    assert len(page) == 1
    assert calls == 2
    assert sleeps == [2.0]


def test_retry_limit_for_5xx(parser_config: ParserConfig) -> None:
    config = ParserConfig(
        request_delay_seconds=0,
        max_retries=1,
        backoff_initial_seconds=0,
        backoff_max_seconds=0,
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500, text="bad")),
        base_url=config.source_base_url,
    )
    source = OpenDotaSource(config, client=client, sleep=lambda _: None)

    try:
        source.fetch_public_matches()
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 500
    else:
        raise AssertionError("Expected HTTPStatusError")


def test_collect_steam_fetches_history_then_details(parser_config: ParserConfig) -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/GetMatchHistory/v1/"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": 1,
                        "num_results": 2,
                        "results_remaining": 0,
                        "matches": [
                            steam_match_history_payload(match_id=900),
                            steam_match_history_payload(match_id=899),
                        ],
                    }
                },
            )
        match_id = int(request.url.params["match_id"])
        return httpx.Response(200, json=steam_match_details_payload(match_id=match_id))

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=parser_config.steam_base_url,
    )
    source = SteamWebApiSource(
        parser_config,
        client=client,
        sleep=lambda _: None,
        api_key="test-key",
    )
    raw_store = RawPublicMatchStore(parser_config.steam_raw_output_dir, schema_version=1)
    checkpoint_store = CheckpointStore(parser_config.steam_checkpoint_file)

    result = collect_steam_matches(
        source=source,
        raw_store=raw_store,
        checkpoint_store=checkpoint_store,
        config=parser_config,
        limit=2,
    )

    assert result.fetched == 2
    assert result.written == 2
    assert result.last_less_than_match_id == 898
    assert requested_paths.count("/IDOTA2Match_570/GetMatchHistory/v1/") == 1
    assert requested_paths.count("/IDOTA2Match_570/GetMatchDetails/v1/") == 2
    assert len(list(parser_config.steam_raw_output_dir.rglob("*.json"))) == 2


def test_collect_steam_skips_match_details_after_repeated_5xx(
    parser_config: ParserConfig,
) -> None:
    config = replace(
        parser_config,
        max_retries=0,
        request_delay_seconds=0,
        backoff_initial_seconds=0,
        backoff_max_seconds=0,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/GetMatchHistory/v1/"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": 1,
                        "num_results": 2,
                        "results_remaining": 0,
                        "matches": [
                            steam_match_history_payload(match_id=900),
                            steam_match_history_payload(match_id=899),
                        ],
                    }
                },
            )
        match_id = int(request.url.params["match_id"])
        if match_id == 900:
            return httpx.Response(500, text="bad")
        return httpx.Response(200, json=steam_match_details_payload(match_id=match_id))

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=config.steam_base_url,
    )
    source = SteamWebApiSource(
        config,
        client=client,
        sleep=lambda _: None,
        api_key="test-key",
    )

    result = collect_steam_matches(
        source=source,
        raw_store=RawPublicMatchStore(config.steam_raw_output_dir, schema_version=1),
        checkpoint_store=CheckpointStore(config.steam_checkpoint_file),
        config=config,
        limit=2,
    )

    assert result.fetched == 1
    assert result.failed == 1
    assert result.written == 1
    assert len(list(config.steam_raw_output_dir.rglob("*.json"))) == 1
