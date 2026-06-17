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
        details_source="steam",
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
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.less_than_match_id == 898


def test_collect_steam_checkpoint_tracks_last_processed_match_not_whole_page(
    parser_config: ParserConfig,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/GetMatchHistory/v1/"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": 1,
                        "num_results": 3,
                        "results_remaining": 10,
                        "matches": [
                            steam_match_history_payload(match_id=902),
                            steam_match_history_payload(match_id=901),
                            steam_match_history_payload(match_id=900),
                        ],
                    }
                },
            )
        match_id = int(request.url.params["match_id"])
        return httpx.Response(200, json=steam_match_details_payload(match_id=match_id))

    source = SteamWebApiSource(
        parser_config,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url=parser_config.steam_base_url,
        ),
        sleep=lambda _: None,
        api_key="test-key",
    )
    checkpoint_store = CheckpointStore(parser_config.steam_checkpoint_file)

    result = collect_steam_matches(
        source=source,
        details_source="steam",
        raw_store=RawPublicMatchStore(parser_config.steam_raw_output_dir, schema_version=1),
        checkpoint_store=checkpoint_store,
        config=parser_config,
        limit=1,
    )

    checkpoint = checkpoint_store.load()
    assert result.fetched == 1
    assert result.last_less_than_match_id == 901
    assert checkpoint is not None
    assert checkpoint.less_than_match_id == 901


def test_collect_steam_skips_match_details_5xx_without_retrying(
    parser_config: ParserConfig,
) -> None:
    config = replace(
        parser_config,
        max_retries=5,
        request_delay_seconds=0,
        backoff_initial_seconds=0,
        backoff_max_seconds=0,
    )
    detail_calls_by_match_id: dict[int, int] = {}

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
        detail_calls_by_match_id[match_id] = detail_calls_by_match_id.get(match_id, 0) + 1
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
        details_source="steam",
        raw_store=RawPublicMatchStore(config.steam_raw_output_dir, schema_version=1),
        checkpoint_store=CheckpointStore(config.steam_checkpoint_file),
        config=config,
        limit=2,
    )

    assert result.fetched == 1
    assert result.failed == 1
    assert result.written == 1
    assert detail_calls_by_match_id == {900: 1, 899: 1}
    assert len(list(config.steam_raw_output_dir.rglob("*.json"))) == 1


def test_collect_steam_counts_failed_details_toward_limit(
    parser_config: ParserConfig,
) -> None:
    config = replace(
        parser_config,
        max_retries=5,
        request_delay_seconds=0,
        backoff_initial_seconds=0,
        backoff_max_seconds=0,
    )
    history_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal history_calls
        if request.url.path.endswith("/GetMatchHistory/v1/"):
            history_calls += 1
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": 1,
                        "num_results": 2,
                        "results_remaining": 10,
                        "matches": [
                            steam_match_history_payload(match_id=900),
                            steam_match_history_payload(match_id=899),
                        ],
                    }
                },
            )
        return httpx.Response(500, text="bad")

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
    checkpoint_store = CheckpointStore(config.steam_checkpoint_file)

    result = collect_steam_matches(
        source=source,
        details_source="steam",
        raw_store=RawPublicMatchStore(config.steam_raw_output_dir, schema_version=1),
        checkpoint_store=checkpoint_store,
        config=config,
        limit=2,
    )

    checkpoint = checkpoint_store.load()
    assert result.fetched == 0
    assert result.failed == 2
    assert result.pages == 1
    assert history_calls == 1
    assert checkpoint is not None
    assert checkpoint.less_than_match_id == 898
    assert len(list(config.steam_raw_output_dir.rglob("*.json"))) == 0


def test_collect_steam_uses_sequence_details_without_calling_match_details(
    parser_config: ParserConfig,
) -> None:
    config = replace(
        parser_config,
        request_delay_seconds=0,
        backoff_initial_seconds=0,
        backoff_max_seconds=0,
    )
    steam_detail_calls = 0
    sequence_starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal steam_detail_calls
        if request.url.path.endswith("/GetMatchHistory/v1/"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": 1,
                        "num_results": 2,
                        "results_remaining": 0,
                        "matches": [
                            steam_match_history_payload(match_id=900, match_seq_num=1900),
                            steam_match_history_payload(match_id=899, match_seq_num=1899),
                        ],
                    }
                },
            )
        if request.url.path.endswith("/GetMatchHistoryBySequenceNum/v1/"):
            start_seq = int(request.url.params["start_at_match_seq_num"])
            sequence_starts.append(start_seq)
            match_id = 900 if start_seq == 1900 else 899
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": 1,
                        "matches": [
                            steam_match_details_payload(
                                match_id=match_id,
                                match_seq_num=start_seq,
                            )["result"]
                        ],
                    }
                },
            )
        steam_detail_calls += 1
        return httpx.Response(500, text="GetMatchDetails should not be called")

    source = SteamWebApiSource(
        config,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url=config.steam_base_url,
        ),
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

    assert result.fetched == 2
    assert result.failed == 0
    assert result.written == 2
    assert steam_detail_calls == 0
    assert sequence_starts == [1900, 1899]
    assert len(list(config.steam_raw_output_dir.rglob("*.json"))) == 2


def test_collect_steam_skips_sequence_details_without_players(
    parser_config: ParserConfig,
) -> None:
    config = replace(
        parser_config,
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
                        "num_results": 1,
                        "results_remaining": 0,
                        "matches": [
                            steam_match_history_payload(match_id=900, match_seq_num=1900)
                        ],
                    }
                },
            )
        if request.url.path.endswith("/GetMatchHistoryBySequenceNum/v1/"):
            return httpx.Response(
                200,
                json={"result": {"status": 1, "matches": [{"match_id": 900}]}},
            )
        return httpx.Response(500, text="GetMatchDetails should not be called")

    source = SteamWebApiSource(
        config,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url=config.steam_base_url,
        ),
        sleep=lambda _: None,
        api_key="test-key",
    )

    result = collect_steam_matches(
        source=source,
        raw_store=RawPublicMatchStore(config.steam_raw_output_dir, schema_version=1),
        checkpoint_store=CheckpointStore(config.steam_checkpoint_file),
        config=config,
        limit=1,
    )

    assert result.fetched == 0
    assert result.failed == 1
    assert len(list(config.steam_raw_output_dir.rglob("*.json"))) == 0


def test_collect_steam_skips_sequence_response_without_requested_match(
    parser_config: ParserConfig,
) -> None:
    config = replace(
        parser_config,
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
                        "num_results": 1,
                        "results_remaining": 0,
                        "matches": [
                            steam_match_history_payload(match_id=900, match_seq_num=1900)
                        ],
                    }
                },
            )
        if request.url.path.endswith("/GetMatchHistoryBySequenceNum/v1/"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": 1,
                        "matches": [
                            steam_match_details_payload(match_id=899, match_seq_num=1899)[
                                "result"
                            ]
                        ],
                    }
                },
            )
        return httpx.Response(500, text="GetMatchDetails should not be called")

    source = SteamWebApiSource(
        config,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url=config.steam_base_url,
        ),
        sleep=lambda _: None,
        api_key="test-key",
    )

    result = collect_steam_matches(
        source=source,
        raw_store=RawPublicMatchStore(config.steam_raw_output_dir, schema_version=1),
        checkpoint_store=CheckpointStore(config.steam_checkpoint_file),
        config=config,
        limit=1,
    )

    assert result.fetched == 0
    assert result.failed == 1
    assert len(list(config.steam_raw_output_dir.rglob("*.json"))) == 0
