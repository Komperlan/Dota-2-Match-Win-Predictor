from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from dataclasses import replace
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
        result = _collect(
            _resolve_collection_config(config, args.patches, args),
            _resolve_limit(args),
        )
        LOGGER.info("Collected public matches: %s", result)
        return 0

    if args.command == "normalize-public":
        result = _normalize(config, args.patches)
        LOGGER.info("Normalized public matches: %s", result)
        return 0

    if args.command == "parse-public":
        collection = _collect(
            _resolve_collection_config(config, args.patches, args),
            _resolve_limit(args),
        )
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
    patch_group = parser.add_mutually_exclusive_group()
    patch_group.add_argument(
        "--patch-family",
        help="Collect only matches at or after the start of this numbered patch family, "
        "for example 7.39 includes 7.39, 7.39b, 7.39c.",
    )
    patch_group.add_argument(
        "--latest-patch-family",
        action="store_true",
        help="Use the latest numbered patch family from the patch registry.",
    )


def _resolve_limit(args: argparse.Namespace) -> int | None:
    if bool(args.all):
        return None
    if args.limit is None:
        return 100
    return int(args.limit)


def _resolve_collection_config(
    config: ParserConfig,
    patches_path: Path,
    args: argparse.Namespace,
) -> ParserConfig:
    patch_family = getattr(args, "patch_family", None)
    latest_patch_family = bool(getattr(args, "latest_patch_family", False))
    if patch_family is None and not latest_patch_family:
        return config

    patch_registry = PatchRegistry.from_yaml(patches_path)
    if latest_patch_family:
        patch_family = patch_registry.latest_numbered_patch_family()
        if patch_family is None:
            msg = "No numbered patch family found in patch registry"
            raise ValueError(msg)

    family_start = patch_registry.patch_family_start(str(patch_family))
    if family_start is None:
        msg = f"Patch family not found in patch registry: {patch_family}"
        raise ValueError(msg)
    return replace(config, collection_min_start_time=family_start)


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
