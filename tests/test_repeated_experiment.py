import json

import pytest

from experiments import run_repeated
from experiments import analyze_repeated


def test_repeated_runner_writes_each_run_and_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(
        run_repeated,
        "load_manifest",
        lambda path: [{"task_id": "task-1", "project": "example"}],
    )
    calls = []

    def fake_run(task, bug_summary, llm_client, run_id):
        calls.append(run_id)
        return {
            "task_id": task["task_id"],
            "generation_duration_seconds": float(len(calls)),
            "token_usage": {"total_token_count": 10},
            "ranking": {"early_detection": {}},
            "candidate_tests": [
                {"oracle": {"matches_oracle": len(calls) == 2}}
            ],
        }

    monkeypatch.setattr(run_repeated, "run_candidate_experiment", fake_run)
    client_factory = lambda: object()

    result = run_repeated.run_repeated(
        "manifest.csv",
        tmp_path,
        ["task-1"],
        2,
        client_factory=client_factory,
        max_total_cost_usd=1.0,
    )

    assert calls == ["task-1-r001", "task-1-r002"]
    assert result["task_summaries"]["task-1"]["runs_with_detection"] == 1
    assert (tmp_path / "task-1" / "task-1-r001.json").is_file()
    summary = json.loads((tmp_path / "repeated-summary.json").read_text(encoding="utf-8"))
    assert summary["repetitions_per_task"] == 2


def test_repeated_runner_requires_explicit_budget_for_multiple_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        run_repeated,
        "load_manifest",
        lambda path: [{"task_id": "task-1", "project": "example"}],
    )

    with pytest.raises(ValueError, match="explicit budget approval"):
        run_repeated.run_repeated(
            "manifest.csv",
            tmp_path,
            ["task-1"],
            2,
            client_factory=lambda: object(),
        )


def test_repeated_analyzer_reports_seeded_detection_and_rank_intervals(tmp_path):
    source = tmp_path / "repeated.json"
    source.write_text(
        json.dumps(
            {
                "protocol_id": "pilot-v1",
                "tasks": ["task-1"],
                "runs": [
                    {
                        "task_id": "task-1",
                        "any_oracle_match": True,
                        "ranking": {"early_detection": {
                            "original": {"normalized_rank": 0.8},
                            "evidenceloop": {"normalized_rank": 0.4},
                        }},
                    },
                    {
                        "task_id": "task-1",
                        "any_oracle_match": False,
                        "ranking": {"early_detection": {
                            "original": {"normalized_rank": 0.6},
                            "evidenceloop": {"normalized_rank": 0.2},
                        }},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    first = analyze_repeated.analyze_repeated(source, bootstrap_samples=100, random_seed=3)
    second = analyze_repeated.analyze_repeated(source, bootstrap_samples=100, random_seed=3)

    assert first == second
    summary = first["task_summaries"]["task-1"]
    assert summary["detection_rate_95ci"]["mean"] == 0.5
    assert summary["paired_rank_difference_vs_original_95ci"]["evidenceloop"]["mean"] == -0.4