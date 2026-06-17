from __future__ import annotations

from datetime import UTC, datetime

from dota_predictor.parser.patches import Patch, PatchRegistry


def test_patch_registry_finds_latest_numbered_patch_family() -> None:
    registry = PatchRegistry(
        [
            Patch(
                patch_id="7.38",
                version="7.38",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                ended_at=datetime(2025, 5, 1, tzinfo=UTC),
                major=True,
            ),
            Patch(
                patch_id="7.39",
                version="7.39",
                started_at=datetime(2025, 5, 1, tzinfo=UTC),
                ended_at=datetime(2025, 6, 1, tzinfo=UTC),
                major=True,
            ),
            Patch(
                patch_id="7.39b",
                version="7.39b",
                started_at=datetime(2025, 6, 1, tzinfo=UTC),
                ended_at=None,
                major=False,
            ),
        ]
    )

    assert registry.latest_numbered_patch_family() == "7.39"


def test_patch_registry_returns_family_start_for_numbered_and_letter_patches() -> None:
    family_start = datetime(2025, 5, 1, tzinfo=UTC)
    registry = PatchRegistry(
        [
            Patch(
                patch_id="7.39",
                version="7.39",
                started_at=family_start,
                ended_at=datetime(2025, 6, 1, tzinfo=UTC),
                major=True,
            ),
            Patch(
                patch_id="7.39b",
                version="7.39b",
                started_at=datetime(2025, 6, 1, tzinfo=UTC),
                ended_at=None,
                major=False,
            ),
            Patch(
                patch_id="7.40",
                version="7.40",
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
                ended_at=None,
                major=True,
            ),
        ]
    )

    assert registry.patch_family_start("7.39") == family_start
