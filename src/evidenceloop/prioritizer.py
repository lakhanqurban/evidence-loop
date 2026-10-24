from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any


@dataclass
class CandidateFeature:
    change_relevance: float = 0.0
    coverage_contribution: float = 0.0
    execution_cost: float = 0.0
    validity: float = 0.0
    redundancy: float = 0.0


def score_candidate(features: CandidateFeature) -> float:
    return (
        1.0 * features.change_relevance
        + 1.0 * features.coverage_contribution
        + 0.5 * features.validity
        - 0.5 * features.execution_cost
        - 0.5 * features.redundancy
    )


def rank_candidates(
    candidates: list[dict[str, Any]],
    random_seed: int = 42,
) -> dict[str, list[str]]:
    """Return baseline orderings using candidate features, never oracle outcomes."""
    candidate_ids = [str(candidate["candidate_id"]) for candidate in candidates]

    def features_for(candidate: dict[str, Any]) -> CandidateFeature:
        raw = candidate.get("features", {})
        if isinstance(raw, CandidateFeature):
            return raw
        return CandidateFeature(**{
            key: float(raw.get(key, 0.0))
            for key in (
                "change_relevance",
                "coverage_contribution",
                "execution_cost",
                "validity",
                "redundancy",
            )
        })

    original = list(candidate_ids)
    shuffled = list(candidate_ids)
    random.Random(random_seed).shuffle(shuffled)

    relevance = sorted(
        candidates,
        key=lambda candidate: (
            features_for(candidate).change_relevance,
            -candidate_ids.index(str(candidate["candidate_id"])),
        ),
        reverse=True,
    )
    evidence_score = sorted(
        candidates,
        key=lambda candidate: score_candidate(features_for(candidate)),
        reverse=True,
    )

    remaining = list(candidates)
    covered: set[str] = set()
    coverage_order: list[str] = []
    while remaining:
        selected = max(
            remaining,
            key=lambda candidate: (
                len(set(candidate.get("coverage", [])) - covered),
                features_for(candidate).coverage_contribution,
                score_candidate(features_for(candidate)),
                -candidate_ids.index(str(candidate["candidate_id"])),
            ),
        )
        candidate_id = str(selected["candidate_id"])
        coverage_order.append(candidate_id)
        covered.update(str(item) for item in selected.get("coverage", []))
        remaining.remove(selected)

    return {
        "original": original,
        "random": shuffled,
        "coverage": coverage_order,
        "change_relevance": [str(item["candidate_id"]) for item in relevance],
        "evidenceloop": [str(item["candidate_id"]) for item in evidence_score],
    }


def first_fault_detection(order: list[str], fault_detecting_candidates: set[str]) -> dict[str, Any]:
    """Measure where an ordering first detects a fault; outcomes are metric inputs only."""
    first_rank = next(
        (rank for rank, candidate_id in enumerate(order, start=1) if candidate_id in fault_detecting_candidates),
        None,
    )
    return {
        "first_fault_rank": first_rank,
        "candidate_count": len(order),
        "normalized_rank": first_rank / len(order) if order and first_rank is not None else None,
    }
