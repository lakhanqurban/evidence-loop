from pathlib import Path

import pytest

from evidenceloop.benchmark import evaluate_oracle, load_manifest, run_command


def test_load_manifest_reads_csv(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "task_id,project,buggy_commit,fixed_commit,setup_command,test_command\n"
        "task-1,example,abc,def,python -m pip install -r requirements.txt,pytest -q\n",
        encoding="utf-8",
    )

    rows = load_manifest(manifest)
    assert rows[0]["task_id"] == "task-1"
    assert rows[0]["project"] == "example"


def test_load_manifest_requires_expected_columns(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "task_id,project\n"
        "task-1,example\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required columns"):
        load_manifest(manifest)


def test_run_command_reports_success_and_failure(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text("print('hello from benchmark')\n", encoding="utf-8")

    success = run_command(f'python "{script}"', cwd=tmp_path)
    assert success["status"] == "PASS"
    assert "hello from benchmark" in success["stdout"]

    failure = run_command('python -c "raise SystemExit(3)"', cwd=tmp_path)
    assert failure["status"] == "FAILURE"
    assert failure["returncode"] == 3


@pytest.mark.parametrize(
    "returncode,output",
    [
        (127, "pytest: command not found"),
        (9009, "'pytest' is not recognized as an internal or external command"),
    ],
)
def test_classifies_missing_test_command_as_environment_failure(returncode, output):
    from evidenceloop.benchmark import _classify_command_status

    assert _classify_command_status(returncode, output, "") == "ENVIRONMENT_FAILURE"


def test_evaluate_oracle_requires_buggy_failure_fixed_success():
    buggy = {"status": "FAILURE", "returncode": 1}
    fixed = {"status": "PASS", "returncode": 0}

    result = evaluate_oracle(buggy, fixed)
    assert result["matches_oracle"] is True
    assert result["buggy_status"] == "FAILURE"
    assert result["fixed_status"] == "PASS"


@pytest.mark.parametrize(
    "status",
    ["COLLECTION_ERROR", "ENVIRONMENT_FAILURE", "TIMEOUT", "SKIPPED", ""],
)
def test_evaluate_oracle_rejects_non_behavioral_buggy_failures(status):
    result = evaluate_oracle({"status": status}, {"status": "PASS"})

    assert result["matches_oracle"] is False


def test_run_revision_skips_test_after_setup_failure(monkeypatch, tmp_path):
    from evidenceloop import benchmark

    calls = []

    def fake_run_command(command, cwd, timeout_seconds=300):
        calls.append(command)
        result = {
            "command": command,
            "cwd": str(cwd),
            "status": "PASS",
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "duration_seconds": 0.0,
        }
        if command == "git rev-parse --short HEAD":
            result["stdout"] = "original\n"
        elif command == "install dependencies":
            result.update(status="FAILURE", returncode=1, stderr="install failed")
        return result

    monkeypatch.setattr(benchmark, "_resolve_repo_path", lambda task: tmp_path)
    monkeypatch.setattr(benchmark, "run_command", fake_run_command)
    task = {"task_id": "task-1", "project": "example", "setup_command": "install dependencies", "test_command": "pytest"}

    result = benchmark.run_revision(task, "buggy")

    assert result["setup"]["status"] == "FAILURE"
    assert result["test"]["status"] == "ENVIRONMENT_FAILURE"
    assert "pytest" not in calls


def test_candidate_revision_uses_task_image_and_restores_original_commit(monkeypatch, tmp_path):
    from evidenceloop import benchmark
    from evidenceloop.executor import ExecutionResult, ExecutionStatus

    commands = []
    execution = {}

    def fake_run_command(command, cwd, timeout_seconds=300):
        commands.append(command)
        return {
            "command": command,
            "cwd": str(cwd),
            "status": "PASS",
            "returncode": 0,
            "stdout": "original\n" if command == "git rev-parse --short HEAD" else "",
            "stderr": "",
            "duration_seconds": 0.0,
        }

    def fake_execute_test_file(test_code, timeout_seconds, repo_path, image, memory_limit_mb):
        execution.update(test_code=test_code, repo_path=repo_path, image=image, memory_limit_mb=memory_limit_mb)
        return ExecutionResult(ExecutionStatus.PASS, returncode=0)

    monkeypatch.setattr(benchmark, "_resolve_repo_path", lambda task: tmp_path)
    monkeypatch.setattr(benchmark, "run_command", fake_run_command)
    monkeypatch.setattr(benchmark, "execute_test_file", fake_execute_test_file)
    task = {"task_id": "task-1", "project": "example", "executor_image": "runner:test"}

    result = benchmark.run_candidate_revision(task, "buggy", "def test_generated(): pass")

    assert result["test"]["status"] == "PASS"
    assert execution == {
        "test_code": "def test_generated(): pass",
        "repo_path": tmp_path,
        "image": "runner:test",
        "memory_limit_mb": 1024,
    }
    assert commands[-1] == "git checkout -q original"
