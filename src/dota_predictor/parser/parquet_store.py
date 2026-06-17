from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dota_predictor.parser.models import MatchRecord


class ParquetMatchWriter:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, records: list[MatchRecord]) -> int:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        if not records:
            return 0

        by_patch: dict[str, list[MatchRecord]] = defaultdict(list)
        for record in _unique_records(records):
            by_patch[record.patch_id].append(record)

        written = 0
        for patch_id, patch_records in sorted(by_patch.items()):
            patch_dir = self.root / f"patch_id={patch_id}"
            patch_dir.mkdir(parents=True, exist_ok=True)
            rows = [_partitioned_row(record) for record in patch_records]
            table = pa.Table.from_pylist(rows)
            pq.write_table(table, patch_dir / "part-00000.parquet")  # type: ignore[no-untyped-call]
            written += len(patch_records)
        return written


def _unique_records(records: list[MatchRecord]) -> list[MatchRecord]:
    unique: dict[int, MatchRecord] = {}
    for record in sorted(records, key=lambda item: item.start_time):
        unique[record.match_id] = record
    return list(unique.values())


def _partitioned_row(record: MatchRecord) -> dict[str, object]:
    row = record.to_parquet_row()
    del row["patch_id"]
    return row
