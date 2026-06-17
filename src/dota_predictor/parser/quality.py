from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dota_predictor.parser.models import now_utc


@dataclass(frozen=True)
class QualityIssue:
    issue_type: str
    match_id: int | None
    payload: dict[str, Any]
    created_at: datetime

    def to_json_line(self) -> str:
        return json.dumps(
            {
                "issue_type": self.issue_type,
                "match_id": self.match_id,
                "payload": self.payload,
                "created_at": self.created_at.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )


class QualityIssueWriter:
    def __init__(self, path: Path, *, reset: bool = False) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if reset:
            self.path.write_text("", encoding="utf-8")

    def write(self, issue: QualityIssue) -> None:
        with self.path.open("a", encoding="utf-8") as file:
            file.write(issue.to_json_line())
            file.write("\n")

    def write_many(self, issues: list[QualityIssue]) -> None:
        if not issues:
            return
        with self.path.open("a", encoding="utf-8") as file:
            for issue in issues:
                file.write(issue.to_json_line())
                file.write("\n")


def make_issue(
    issue_type: str,
    *,
    match_id: int | None,
    payload: dict[str, Any],
) -> QualityIssue:
    return QualityIssue(
        issue_type=issue_type,
        match_id=match_id,
        payload=payload,
        created_at=now_utc(),
    )
