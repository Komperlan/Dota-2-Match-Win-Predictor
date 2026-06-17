from __future__ import annotations

import httpx

from dota_predictor.parser.checkpoint import CheckpointStore
from dota_predictor.parser.collector import collect_public_matches
from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.raw_store import RawPublicMatchStore
from dota_predictor.parser.source import OpenDotaSource

from .conftest import public_match_payload


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
