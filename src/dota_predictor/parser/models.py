from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class RawPublicMatch:
    match_id: int
    match_seq_num: int | None
    radiant_win: bool | None
    start_time: int
    duration: int | None
    lobby_type: int | None
    game_mode: int | None
    avg_rank_tier: int | None
    num_rank_tier: int | None
    cluster: int | None
    radiant_team: tuple[int, ...]
    dire_team: tuple[int, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RawPublicMatch:
        return cls(
            match_id=int(payload["match_id"]),
            match_seq_num=_optional_int(payload.get("match_seq_num")),
            radiant_win=_optional_bool(payload.get("radiant_win")),
            start_time=int(payload["start_time"]),
            duration=_optional_int(payload.get("duration")),
            lobby_type=_optional_int(payload.get("lobby_type")),
            game_mode=_optional_int(payload.get("game_mode")),
            avg_rank_tier=_optional_int(payload.get("avg_rank_tier")),
            num_rank_tier=_optional_int(payload.get("num_rank_tier")),
            cluster=_optional_int(payload.get("cluster")),
            radiant_team=_team_tuple(payload.get("radiant_team")),
            dire_team=_team_tuple(payload.get("dire_team")),
        )


@dataclass(frozen=True)
class RawSteamMatchDetails:
    match_id: int
    match_seq_num: int | None
    radiant_win: bool | None
    start_time: int
    duration: int | None
    lobby_type: int | None
    game_mode: int | None
    cluster: int | None
    players: tuple[dict[str, Any], ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RawSteamMatchDetails:
        result = payload.get("result", payload)
        if not isinstance(result, dict):
            msg = "Steam match details payload must contain a result object"
            raise ValueError(msg)
        players = result.get("players")
        if not isinstance(players, list | tuple):
            msg = "Steam match details result.players must be a list"
            raise ValueError(msg)
        return cls(
            match_id=int(result["match_id"]),
            match_seq_num=_optional_int(result.get("match_seq_num")),
            radiant_win=_optional_bool(result.get("radiant_win")),
            start_time=int(result["start_time"]),
            duration=_optional_int(result.get("duration")),
            lobby_type=_optional_int(result.get("lobby_type")),
            game_mode=_optional_int(result.get("game_mode")),
            cluster=_optional_int(result.get("cluster")),
            players=tuple(_player_mapping(player) for player in players),
        )

    @property
    def radiant_team(self) -> tuple[int, ...]:
        return _team_from_player_slots(self.players, is_dire=False)

    @property
    def dire_team(self) -> tuple[int, ...]:
        return _team_from_player_slots(self.players, is_dire=True)

    @property
    def has_leaver(self) -> bool | None:
        leaver_statuses = [
            int(player["leaver_status"])
            for player in self.players
            if player.get("leaver_status") is not None
        ]
        if not leaver_statuses:
            return None
        return any(status in {2, 3, 4, 6} for status in leaver_statuses)


@dataclass(frozen=True)
class MatchRecord:
    match_id: int
    source: str
    start_time: datetime
    patch_id: str
    radiant_heroes: tuple[int, int, int, int, int]
    dire_heroes: tuple[int, int, int, int, int]
    radiant_win: bool
    avg_rank_tier: int | None
    radiant_avg_mmr: float | None
    dire_avg_mmr: float | None
    region: int | None
    game_mode: int | None
    lobby_type: int | None
    duration: int | None
    has_leaver: bool | None
    collected_at: datetime
    schema_version: int

    def to_parquet_row(self) -> dict[str, object]:
        return {
            "match_id": self.match_id,
            "source": self.source,
            "start_time": self.start_time,
            "patch_id": self.patch_id,
            "radiant_heroes": list(self.radiant_heroes),
            "dire_heroes": list(self.dire_heroes),
            "radiant_win": self.radiant_win,
            "avg_rank_tier": self.avg_rank_tier,
            "radiant_avg_mmr": self.radiant_avg_mmr,
            "dire_avg_mmr": self.dire_avg_mmr,
            "region": self.region,
            "game_mode": self.game_mode,
            "lobby_type": self.lobby_type,
            "duration": self.duration,
            "has_leaver": self.has_leaver,
            "collected_at": self.collected_at,
            "schema_version": self.schema_version,
        }


def unix_seconds_to_utc(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        return int(value)
    msg = f"Expected int-compatible value, got {type(value).__name__}"
    raise ValueError(msg)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    msg = f"Expected bool or null, got {type(value).__name__}"
    raise ValueError(msg)


def _team_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list | tuple):
        msg = "Team field must be a list"
        raise ValueError(msg)
    return tuple(int(hero_id) for hero_id in value)


def _player_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        msg = "Player entry must be an object"
        raise ValueError(msg)
    return value


def _team_from_player_slots(
    players: tuple[dict[str, Any], ...],
    *,
    is_dire: bool,
) -> tuple[int, ...]:
    team_players: list[tuple[int, int]] = []
    for player in players:
        player_slot = int(player["player_slot"])
        player_is_dire = bool(player_slot & 128)
        if player_is_dire == is_dire:
            team_players.append((player_slot & 7, int(player["hero_id"])))
    return tuple(hero_id for _slot, hero_id in sorted(team_players))
