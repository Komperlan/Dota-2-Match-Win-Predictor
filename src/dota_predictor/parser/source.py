from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from dota_predictor.parser.config import ParserConfig

LOGGER = logging.getLogger(__name__)


class OpenDotaSource:
    source_name = "opendota"

    def __init__(
        self,
        config: ParserConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        api_key: str | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(
            base_url=config.source_base_url,
            timeout=config.timeout_seconds,
        )
        self._owns_client = client is None
        self._sleep = sleep
        self._api_key = api_key if api_key is not None else os.getenv("OPENDOTA_API_KEY")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenDotaSource:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def endpoint(self) -> str:
        return self.config.public_matches_endpoint

    def fetch_public_matches(
        self,
        *,
        less_than_match_id: int | None = None,
        min_rank: int | None = None,
        max_rank: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, int | str] = {}
        if less_than_match_id is not None:
            params["less_than_match_id"] = less_than_match_id
        if min_rank is not None:
            params["min_rank"] = min_rank
        if max_rank is not None:
            params["max_rank"] = max_rank
        if self._api_key:
            params["api_key"] = self._api_key

        response = self._request("GET", self.endpoint, params=params)
        payload = response.json()
        if not isinstance(payload, list):
            msg = "OpenDota /publicMatches response must be a list"
            raise ValueError(msg)
        return [_ensure_mapping(item) for item in payload]

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, int | str],
    ) -> httpx.Response:
        attempt = 0
        while True:
            response = self._client.request(method, url, params=params)
            if not _is_retryable(response.status_code):
                response.raise_for_status()
                self._sleep_after_success()
                return response

            attempt += 1
            if attempt > self.config.max_retries:
                response.raise_for_status()

            delay = _retry_delay(
                response,
                attempt=attempt,
                initial=self.config.backoff_initial_seconds,
                maximum=self.config.backoff_max_seconds,
            )
            LOGGER.warning(
                "OpenDota request failed with %s; retrying in %.2fs",
                response.status_code,
                delay,
            )
            self._sleep(delay)

    def _sleep_after_success(self) -> None:
        if self.config.request_delay_seconds > 0:
            self._sleep(self.config.request_delay_seconds)


class SteamWebApiSource:
    source_name = "steam"

    def __init__(
        self,
        config: ParserConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        api_key: str | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(
            base_url=config.steam_base_url,
            timeout=config.timeout_seconds,
        )
        self._owns_client = client is None
        self._sleep = sleep
        self._api_key = api_key if api_key is not None else os.getenv("STEAM_WEB_API_KEY")
        if not self._api_key:
            msg = "Steam Web API requires STEAM_WEB_API_KEY"
            raise ValueError(msg)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SteamWebApiSource:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def match_history_endpoint(self) -> str:
        return self.config.steam_match_history_endpoint

    @property
    def match_history_by_sequence_endpoint(self) -> str:
        return self.config.steam_match_history_by_sequence_endpoint

    @property
    def match_details_endpoint(self) -> str:
        return self.config.steam_match_details_endpoint

    def fetch_match_history(
        self,
        *,
        start_at_match_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, int | str] = {
            "key": self._api_key or "",
            "matches_requested": self.config.steam_matches_requested,
        }
        if start_at_match_id is not None:
            params["start_at_match_id"] = start_at_match_id
        if self.config.steam_history_game_mode is not None:
            params["game_mode"] = self.config.steam_history_game_mode
        if self.config.steam_history_min_players is not None:
            params["min_players"] = self.config.steam_history_min_players

        response = self._request("GET", self.match_history_endpoint, params=params)
        payload = _ensure_mapping(response.json())
        result = _ensure_mapping(payload.get("result"))
        if int(result.get("status", 0)) != 1:
            msg = f"Steam GetMatchHistory returned status={result.get('status')}"
            raise ValueError(msg)
        return result

    def fetch_match_history_by_sequence(
        self,
        *,
        start_at_match_seq_num: int,
        matches_requested: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, int | str] = {
            "key": self._api_key or "",
            "start_at_match_seq_num": start_at_match_seq_num,
            "matches_requested": matches_requested,
        }
        response = self._request(
            "GET",
            self.match_history_by_sequence_endpoint,
            params=params,
        )
        payload = _ensure_mapping(response.json())
        result = _ensure_mapping(payload.get("result"))
        if int(result.get("status", 0)) != 1:
            msg = f"Steam GetMatchHistoryBySequenceNum returned status={result.get('status')}"
            raise ValueError(msg)
        return result

    def fetch_match_details(self, *, match_id: int) -> dict[str, Any]:
        params: dict[str, int | str] = {
            "key": self._api_key or "",
            "match_id": match_id,
        }
        response = self._request(
            "GET",
            self.match_details_endpoint,
            params=params,
            retry_server_errors=False,
        )
        return _ensure_mapping(response.json())

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, int | str],
        retry_server_errors: bool = True,
    ) -> httpx.Response:
        attempt = 0
        while True:
            response = self._client.request(method, url, params=params)
            if not _is_retryable(
                response.status_code,
                retry_server_errors=retry_server_errors,
            ):
                response.raise_for_status()
                self._sleep_after_success()
                return response

            attempt += 1
            if attempt > self.config.max_retries:
                response.raise_for_status()

            delay = _retry_delay(
                response,
                attempt=attempt,
                initial=self.config.backoff_initial_seconds,
                maximum=self.config.backoff_max_seconds,
            )
            LOGGER.warning(
                "Steam Web API request failed with %s; retrying in %.2fs",
                response.status_code,
                delay,
            )
            self._sleep(delay)

    def _sleep_after_success(self) -> None:
        if self.config.request_delay_seconds > 0:
            self._sleep(self.config.request_delay_seconds)


def _is_retryable(status_code: int, *, retry_server_errors: bool = True) -> bool:
    return status_code == 429 or (
        retry_server_errors and 500 <= status_code <= 599
    )


def _retry_delay(
    response: httpx.Response,
    *,
    attempt: int,
    initial: float,
    maximum: float,
) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(str(retry_after)))
        except ValueError:
            LOGGER.debug("Ignoring invalid Retry-After header: %s", retry_after)
    delay = initial * float(2 ** (attempt - 1))
    return delay if delay < maximum else maximum


def _ensure_mapping(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        msg = "OpenDota /publicMatches items must be objects"
        raise ValueError(msg)
    return item
