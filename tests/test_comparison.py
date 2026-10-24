import json

import pytest

from experiments import run_comparison


def test_comparison_runs_all_conditions_and_persists_artifacts(monkeypatch, tmp_path):
    task = {
        "task_id": "task-1",
        "project": "example",
        "buggy_commit": "buggy",
        "fixed_commit": "fixed",
        "test_command": "pytest default",
        "baseline_test_command": "pytest original",
    }
    monkeypatch.setattr(run_comparison, "load_manifest", lambda path: [task])
    seen_commands = []

    def fake_run_task(task, timeout_seconds, revision):
        seen_commands.append(task["test_command"])
        return {"test": {"status": "PASS"}, "status": "PASS"}

    monkeypatch.setattr(run_comparison, "run_task", fake_run_task)
    seen_conditions = []

    def fake_experiment(task, bug_summary, llm_client, run_id, condition):
        seen_conditions.append(condition)
        return {
            "task_id": task["task_id"],
            "condition": condition,
            "candidate_tests": [],
            "ranking": {"enabled": condition == "full"},
        }

    monkeypatch.setattr(run_comparison, "run_candidate_experiment", fake_experiment)

    result = run_comparison.run_comparison(
        "manifest.csv",
        tmp_path,
        ["task-1"],
        repetitions=1,
        max_total_cost_usd=1.0,
        client_factory=lambda: object(),
    )

    assert seen_commands == ["pytest original", "pytest original"]
    assert seen_conditions == ["one_shot", "retrieval", "feedback", "full"]
    assert len(result["records"]) == 5
    assert json.loads((tmp_path / "comparison-summary.json").read_text(encoding="utf-8"))["conditions"] == list(run_comparison.CONDITIONS)


def test_comparison_requires_explicit_cost_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(run_comparison, "load_manifest", lambda path: [{"task_id": "task-1"}])

    with pytest.raises(ValueError, match="explicit --max-total-cost-usd"):
        run_comparison.run_comparison("manifest.csv", tmp_path, ["task-1"])