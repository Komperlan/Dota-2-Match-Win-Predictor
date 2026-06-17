from __future__ import annotations

import pyarrow.parquet as pq

from dota_predictor.parser.config import ParserConfig
from dota_predictor.parser.normalizer import normalize_public_matches
from dota_predictor.parser.parquet_store import ParquetMatchWriter
from dota_predictor.parser.patches import PatchRegistry
from dota_predictor.parser.quality import QualityIssueWriter
from dota_predictor.parser.raw_store import RawPublicMatchStore

from .conftest import public_match_payload


def test_normalized_parquet_contains_unique_match_ids(
    parser_config: ParserConfig,
    patch_registry: PatchRegistry,
) -> None:
    raw_store = RawPublicMatchStore(parser_config.raw_output_dir, schema_version=1)
    raw_store.save(
        public_match_payload(match_id=500),
        source="opendota",
        endpoint="/publicMatches",
    )
    raw_store.save(
        public_match_payload(match_id=501),
        source="opendota",
        endpoint="/publicMatches",
    )

    result = normalize_public_matches(
        raw_store=raw_store,
        parquet_writer=ParquetMatchWriter(parser_config.normalized_output_dir),
        issue_writer=QualityIssueWriter(parser_config.quality_issues_file, reset=True),
        patch_registry=patch_registry,
        config=parser_config,
    )

    table = pq.read_table(parser_config.normalized_output_dir)
    match_ids = table.column("match_id").to_pylist()
    patch_ids = table.column("patch_id").to_pylist()
    assert result.normalized == 2
    assert sorted(match_ids) == [500, 501]
    assert patch_ids == ["test-patch", "test-patch"]
