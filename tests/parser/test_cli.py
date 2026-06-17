from __future__ import annotations

import logging
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from dota_predictor.parser.cli import _configure_logging, _resolve_collection_config
from dota_predictor.parser.config import ParserConfig


def test_resolve_collection_config_accepts_trailing_dot_patch_family(
    tmp_path: Path,
    parser_config: ParserConfig,
) -> None:
    patches_path = tmp_path / "patches.yaml"
    patches_path.write_text(
        """
patches:
  - patch_id: "7.41"
    version: "7.41"
    started_at: "2026-03-24T07:00:00Z"
    ended_at: null
    major: true
""",
        encoding="utf-8",
    )

    config = _resolve_collection_config(
        parser_config,
        patches_path,
        Namespace(patch_family="7.41.", latest_patch_family=False),
    )

    assert config.collection_min_start_time == datetime(2026, 3, 24, 7, tzinfo=UTC)


def test_configure_logging_suppresses_http_client_info_logs() -> None:
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    logging.getLogger("httpcore").setLevel(logging.NOTSET)

    _configure_logging("INFO")

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
