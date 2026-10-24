from types import SimpleNamespace

from evidenceloop import executor
from evidenceloop.executor import ExecutionStatus, execute_test_file


def test_executor_fails_closed_when_docker_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.shutil, "which", lambda command: None)

    result = execute_test_file("def test_ok():\n    assert True", repo_path=tmp_path)

    assert result.status == ExecutionStatus.ENVIRONMENT_FAILURE
    assert "Docker" in result.stderr


def test_executor_uses_restricted_docker_container(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(executor.shutil, "which", lambda command: "docker")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    result = execute_test_file("def test_ok():\n    assert True", repo_path=tmp_path)
    command = captured["command"]

    assert result.status == ExecutionStatus.PASS
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--memory") + 1] == "1024m"
    assert command[command.index("--pids-limit") + 1] == "64"
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert captured["kwargs"]["shell"] is False


def test_executor_classifies_pytest_assertion_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.shutil, "which", lambda command: "docker")
    monkeypatch.setattr(
        executor.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="E       AssertionError: assert False\n1 failed in 0.02s",
            stderr="",
        ),
    )

    result = execute_test_file("def test_fail():\n    assert False", repo_path=tmp_path)

    assert result.status == ExecutionStatus.ASSERTION_FAILURE


def test_executor_classifies_runtime_exception_as_execution_error(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.shutil, "which", lambda command: "docker")
    monkeypatch.setattr(
        executor.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=(
                "Traceback (most recent call last):\n"
                "  File \"test_generated.py\", line 4, in test_write\n"
                "UnicodeEncodeError: 'ascii' codec can't encode character\n"
                "1 failed in 0.02s"
            ),
            stderr="",
        ),
    )

    result = execute_test_file("def test_write():\n    pass", repo_path=tmp_path)

    assert result.status == ExecutionStatus.EXECUTION_ERROR


def test_executor_extracts_measured_coverage_files(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.shutil, "which", lambda command: "docker")
    monkeypatch.setattr(
        executor.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="Name                   Stmts   Miss  Cover   Missing\nblack.py                 100      5    95%\n",
            stderr="",
        ),
    )

    result = execute_test_file("def test_ok():\n    assert True", repo_path=tmp_path)

    assert result.coverage == ["black.py"]


def test_sandbox_copy_excludes_common_secret_paths():
    names = [
        ".env",
        ".env.example",
        ".secrets",
        ".ssh",
        "credentials.json",
        "id_rsa",
        "service-account.json",
        "secrets.env",
        "private.pem",
    ]

    ignored = executor._ignore_sandbox_files(".", names)

    assert set(names) == ignored