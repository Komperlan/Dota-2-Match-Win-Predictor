from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from dota_predictor.parser.checkpoint import CheckpointStore
from dota_predictor.parser.collector import collect_public_matches
from dota_predictor.parser.config import ParserConfig, load_parser_config
from dota_predictor.parser.normalizer import normalize_public_matches
from dota_predictor.parser.parquet_store import ParquetMatchWriter
from dota_predictor.parser.patches import PatchRegistry
from dota_predictor.parser.quality import QualityIssueWriter
from dota_predictor.parser.raw_store import RawPublicMatchStore
from dota_predictor.parser.source import OpenDotaSource

LOGGER = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper()))

    config = load_parser_config(args.config)
    if args.command == "collect-public":
        result = _collect(config, _resolve_limit(args))
        LOGGER.info("Collected public matches: %s", result)
        return 0

    if args.command == "normalize-public":
        result = _normalize(config, args.patches)
        LOGGER.info("Normalized public matches: %s", result)
        return 0

    if args.command == "parse-public":
        collection = _collect(config, _resolve_limit(args))
        normalization = _normalize(config, args.patches)
        LOGGER.info("Collected public matches: %s", collection)
        LOGGER.info("Normalized public matches: %s", normalization)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dota-parser")
    parser.add_argument("--config", type=Path, default=Path("configs/parser.yaml"))
    parser.add_argument("--patches", type=Path, default=Path("configs/patches.yaml"))
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect-public")
    _add_collection_limit_flags(collect)

    subparsers.add_parser("normalize-public")

    parse = subparsers.add_parser("parse-public")
    _add_collection_limit_flags(parse)
    return parser


def _collect(config: ParserConfig, limit: int | None) -> object:
    raw_store = RawPublicMatchStore(config.raw_output_dir, schema_version=config.schema_version)
    checkpoint_store = CheckpointStore(config.checkpoint_file)
    with OpenDotaSource(config) as source:
        return collect_public_matches(
            source=source,
            raw_store=raw_store,
            checkpoint_store=checkpoint_store,
            config=config,
            limit=limit,
        )


def _add_collection_limit_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of public match rows to process in this run. Default: 100.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Keep paginating until OpenDota returns an empty page.",
    )


def _resolve_limit(args: argparse.Namespace) -> int | None:
    if bool(args.all):
        return None
    if args.limit is None:
        return 100
    return int(args.limit)


def _normalize(config: ParserConfig, patches_path: Path) -> object:
    raw_store = RawPublicMatchStore(config.raw_output_dir, schema_version=config.schema_version)
    parquet_writer = ParquetMatchWriter(config.normalized_output_dir)
    issue_writer = QualityIssueWriter(config.quality_issues_file, reset=True)
    patch_registry = PatchRegistry.from_yaml(patches_path)
    return normalize_public_matches(
        raw_store=raw_store,
        parquet_writer=parquet_writer,
        issue_writer=issue_writer,
        patch_registry=patch_registry,
        config=config,
    )


if __name__ == "__main__":
    raise SystemExit(main())
