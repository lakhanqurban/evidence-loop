from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    evidence_id: str
    type: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    commit: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class EvidenceStore:
    def __init__(self) -> None:
        self._items: list[Evidence] = []

    def add(self, evidence: Evidence) -> Evidence:
        self._items.append(evidence)
        return evidence

    def add_many(self, evidence_items: list[Evidence]) -> list[Evidence]:
        self._items.extend(evidence_items)
        return evidence_items

    def evidence_ids(self) -> list[str]:
        return [item.evidence_id for item in self._items]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": item.evidence_id,
                "type": item.type,
                "path": item.path,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "commit": item.commit,
                "content": item.content,
                "metadata": item.metadata,
            }
            for item in self._items
        ]
