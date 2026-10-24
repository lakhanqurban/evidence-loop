import json

from experiments import analyze_results, run_experiment


def test_run_experiment_executes_both_revisions_and_writes_artifact(monkeypatch, tmp_path):
    task = {
        "task_id": "task-1",
        "project": "example",
        "buggy_commit": "buggy",
        "fixed_commit": "fixed",
    }
    monkeypatch.setattr(run_experiment, "load_manifest", lambda path: [task])
    monkeypatch.setattr(
        run_experiment,
        "run_task",
        lambda task, timeout_seconds, revision: {
            "task_id": task["task_id"],
            "test": {"status": "FAILURE" if revision == "buggy" else "PASS"},
        },
    )
    output = tmp_path / "run.json"

    payload = run_experiment.run(tmp_path / "manifest.csv", output)

    assert payload["tasks"][0]["oracle"]["matches_oracle"] is True
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_analyze_results_summarizes_oracle_and_statuses(tmp_path):
    input_path = tmp_path / "run.json"
    input_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "oracle": {"matches_oracle": True},
                        "buggy": {"test": {"status": "FAILURE"}},
                        "fixed": {"test": {"status": "PASS"}},
                    },
                    {
                        "oracle": {"matches_oracle": False},
                        "buggy": {"test": {"status": "ENVIRONMENT_FAILURE"}},
                        "fixed": {"test": {"status": "PASS"}},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = analyze_results.analyze(input_path)

    assert summary["task_count"] == 2
    assert summary["oracle_matches"] == 1
    assert summary["buggy_statuses"] == {"FAILURE": 1, "ENVIRONMENT_FAILURE": 1}