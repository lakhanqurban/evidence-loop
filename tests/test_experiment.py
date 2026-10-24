from evidenceloop import experiment


def test_candidate_experiment_generates_on_buggy_then_evaluates_candidate(monkeypatch, tmp_path):
    state = {"revision": "original"}
    task = {
        "task_id": "task-1",
        "project": "example",
        "buggy_commit": "buggy-rev",
        "fixed_commit": "fixed-rev",
    }
    calls = []

    def fake_run_command(command, cwd, timeout_seconds=300):
        if command == "git rev-parse --short HEAD":
            stdout = "original-rev\n"
        else:
            revision = command.removeprefix("git checkout -q ")
            state["revision"] = "buggy" if revision == "buggy-rev" else "original"
            stdout = ""
        return {
            "command": command,
            "cwd": str(cwd),
            "status": "PASS",
            "returncode": 0,
            "stdout": stdout,
            "stderr": "",
            "duration_seconds": 0.0,
        }

    class StubGenerator:
        def __init__(self, llm_client):
            pass

        def generate(self, changed_files, source_context, related_tests, bug_summary):
            assert state["revision"] == "buggy"
            assert changed_files == ["src/target.py"]
            assert "buggy implementation" in source_context
            assert "fixed implementation" not in source_context
            assert "bug report" == bug_summary
            return ["def test_candidate():\n    assert True"]

    def fake_run_candidate_task(task, test_code, timeout_seconds, memory_limit_mb):
        assert timeout_seconds == 60
        assert memory_limit_mb == 2048
        calls.append(test_code)
        return {
            "buggy": {"test": {"status": "ASSERTION_FAILURE"}},
            "fixed": {"test": {"status": "PASS"}},
            "oracle": {"matches_oracle": True},
        }

    monkeypatch.setattr(experiment, "_resolve_repo_path", lambda task: tmp_path)
    monkeypatch.setattr(experiment, "run_command", fake_run_command)
    monkeypatch.setattr(experiment, "get_changed_files", lambda *args: ["src/target.py"])
    monkeypatch.setattr(experiment, "find_test_files", lambda *args: ["tests/test_target.py"])
    monkeypatch.setattr(experiment, "read_source_file", lambda repo, path: "buggy implementation")
    monkeypatch.setattr(experiment, "CandidateGenerator", StubGenerator)
    monkeypatch.setattr(experiment, "run_candidate_task", fake_run_candidate_task)

    result = experiment.run_candidate_experiment(task, "bug report", llm_client=object())

    assert result["candidate_tests"][0]["oracle"]["matches_oracle"] is True
    assert result["evidence"]["items"][0]["evidence_id"].startswith("ev-")
    assert result["candidate_tests"][0]["evidence_ids"] == [
        item["evidence_id"] for item in result["evidence"]["items"]
    ]
    assert calls == ["def test_candidate():\n    assert True"]
    assert state["revision"] == "original"


def test_refinement_gets_buggy_feedback_only_and_records_behavioral_gain(monkeypatch, tmp_path):
    task = {
        "task_id": "task-refine",
        "project": "example",
        "buggy_commit": "buggy-rev",
        "fixed_commit": "fixed-rev",
    }
    received_feedback = []

    def fake_run_command(command, cwd, timeout_seconds=300):
        return {
            "command": command,
            "cwd": str(cwd),
            "status": "PASS",
            "returncode": 0,
            "stdout": "original-rev\n" if command == "git rev-parse --short HEAD" else "",
            "stderr": "",
            "duration_seconds": 0.0,
        }

    class RefiningGenerator:
        def __init__(self, llm_client):
            pass

        def generate(self, **kwargs):
            return ["def test_initial():\n    assert True"]

        def refine(self, candidate, buggy_feedback, **kwargs):
            received_feedback.append(buggy_feedback)
            return ["def test_refined():\n    assert False"]

    def fake_run_candidate_task(task, test_code, timeout_seconds, memory_limit_mb):
        improved = "refined" in test_code
        return {
            "buggy": {"test": {
                "status": "ASSERTION_FAILURE" if improved else "PASS",
                "stdout": "assertion observed" if improved else "1 passed in 0.01s",
                "stderr": "",
            }},
            "fixed": {"test": {"status": "PASS", "stdout": "fixed secret output", "stderr": ""}},
            "oracle": {"matches_oracle": improved},
        }

    monkeypatch.setattr(experiment, "_resolve_repo_path", lambda task: tmp_path)
    monkeypatch.setattr(experiment, "run_command", fake_run_command)
    monkeypatch.setattr(experiment, "run_candidate_task", fake_run_candidate_task)
    monkeypatch.setattr(experiment, "get_changed_files", lambda *args: ["src/module.py"])
    monkeypatch.setattr(experiment, "find_test_files", lambda *args: [])
    monkeypatch.setattr(experiment, "read_source_file", lambda repo, path: "buggy implementation")
    monkeypatch.setattr(experiment, "CandidateGenerator", RefiningGenerator)

    result = experiment.run_candidate_experiment(task, llm_client=object())

    assert received_feedback == [{"status": "PASS", "stdout": "1 passed in 0.01s", "stderr": ""}]
    assert result["refinement"]["attempted"] is True
    assert result["refinement"]["behavioral_improvements"] == 1
    assert result["refinement"]["repair_attempts"] == 0
    assert result["candidate_tests"][1]["oracle"]["matches_oracle"] is True