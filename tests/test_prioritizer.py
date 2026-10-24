from evidenceloop.prioritizer import (
    CandidateFeature,
    first_fault_detection,
    rank_candidates,
    score_candidate,
)


def test_score_candidate():
    features = CandidateFeature(change_relevance=1.0, coverage_contribution=1.0, execution_cost=0.1, validity=1.0, redundancy=0.2)
    score = score_candidate(features)
    assert score > 0


def test_rank_candidates_returns_reproducible_baselines_without_oracle_inputs():
    candidates = [
        {
            "candidate_id": "c1",
            "features": {"change_relevance": 0.1, "coverage_contribution": 1.0, "validity": 1.0},
            "coverage": ["a", "b"],
        },
        {
            "candidate_id": "c2",
            "features": {"change_relevance": 0.9, "coverage_contribution": 0.5, "validity": 1.0},
            "coverage": ["b", "c"],
        },
        {
            "candidate_id": "c3",
            "features": {"change_relevance": 0.5, "coverage_contribution": 0.2, "validity": 1.0},
            "coverage": ["c"],
        },
    ]

    first = rank_candidates(candidates, random_seed=7)
    second = rank_candidates(candidates, random_seed=7)

    assert first == second
    assert first["original"] == ["c1", "c2", "c3"]
    assert first["change_relevance"][0] == "c2"
    assert set(first) == {"original", "random", "coverage", "change_relevance", "evidenceloop"}


def test_first_fault_detection_reports_rank_and_normalized_position():
    metrics = first_fault_detection(["c1", "c2", "c3", "c4"], {"c3"})

    assert metrics == {"first_fault_rank": 3, "candidate_count": 4, "normalized_rank": 0.75}
