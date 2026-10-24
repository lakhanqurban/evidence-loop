import json

from typer.testing import CliRunner

from evidenceloop import cli


def test_generate_calls_generator_and_returns_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_changed_files", lambda *args: ["src/example.py"])
    monkeypatch.setattr(cli, "find_test_files", lambda *args: ["tests/test_example.py"])
    monkeypatch.setattr(
        cli,
        "read_source_file",
        lambda repo, file_name: f"contents for {file_name}",
    )

    class StubGenerator:
        def __init__(self, llm_client):
            pass

        def generate(self, changed_files, source_context, related_tests, bug_summary):
            assert changed_files == ["src/example.py"]
            assert "contents for src/example.py" in source_context
            assert "contents for tests/test_example.py" in related_tests
            assert bug_summary == "expected behavior"
            return ["def test_regression():\n    assert True"]

    monkeypatch.setattr(cli, "CandidateGenerator", StubGenerator)
    output_path = tmp_path / "artifacts" / "candidate.json"
    result = CliRunner().invoke(
        cli.app,
        [
            "generate",
            str(tmp_path),
            "base",
            "target",
            "--bug-summary",
            "expected behavior",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["prompt_version"] == "v2"
    assert payload["candidate_tests"][0]["syntax_valid"] is True
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_experiment_command_persists_candidate_evaluation(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("header\n", encoding="utf-8")
    payload = {"task_id": "task-1", "candidate_tests": []}
    monkeypatch.setattr(
        cli,
        "load_manifest",
        lambda path: [{"task_id": "task-1", "project": "example"}],
    )
    monkeypatch.setattr(
        cli,
        "run_candidate_experiment",
        lambda task, bug_summary=None: payload,
    )
    output = tmp_path / "artifacts" / "experiment.json"

    result = CliRunner().invoke(
        cli.app,
        [
            "experiment",
            "task-1",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text(encoding="utf-8")) == payload