from __future__ import annotations

import csv
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from evidenceloop.executor import ExecutionStatus, execute_test_file

REQUIRED_COLUMNS = {
    "task_id",
    "project",
    "buggy_commit",
    "fixed_commit",
    "setup_command",
    "test_command",
}


def _classify_command_status(returncode: int, stdout: str, stderr: str) -> str:
    output = (stdout or "") + "\n" + (stderr or "")
    if returncode == 0:
        return "PASS"
    lowered_output = output.lower()
    if returncode in {126, 127, 9009} or any(
        marker in lowered_output
        for marker in (
            "command not found",
            "is not recognized as an internal or external command",
            "no such file or directory",
            "cannot find the path specified",
        )
    ):
        return "ENVIRONMENT_FAILURE"
    if "ERROR collecting" in output or "ImportError" in output or "ModuleNotFoundError" in output:
        return "COLLECTION_ERROR"
    if "Traceback" in output:
        return "EXECUTION_ERROR"
    if "timed out" in output.lower() or "timeout" in output.lower():
        return "TIMEOUT"
    return "FAILURE"


def run_command(command: str, cwd: str | Path, timeout_seconds: int = 300) -> dict[str, Any]:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, "PYTHONPATH": str(Path(cwd))},
        )
        duration = time.monotonic() - start
        return {
            "command": command,
            "cwd": str(cwd),
            "status": _classify_command_status(completed.returncode, completed.stdout, completed.stderr),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_seconds": round(duration, 3),
        }
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return {
            "command": command,
            "cwd": str(cwd),
            "status": "TIMEOUT",
            "returncode": 124,
            "stdout": stdout,
            "stderr": stderr,
            "duration_seconds": round(duration, 3),
        }


def evaluate_oracle(buggy_result: dict[str, Any], fixed_result: dict[str, Any]) -> dict[str, Any]:
    buggy_status = str(buggy_result.get("status", "")).upper()
    fixed_status = str(fixed_result.get("status", "")).upper()

    behavior_failure_statuses = {"ASSERTION_FAILURE", "EXECUTION_ERROR", "FAILURE"}
    failure_output = "\n".join(
        str(buggy_result.get(key, "")) for key in ("stdout", "stderr")
    ).lower()
    infrastructure_markers = (
        "cannot connect to the docker daemon",
        "no such file or directory",
        "command not found",
        "is not recognized as an internal or external command",
        "no module named pytest",
        "error collecting",
        "modulenotfounderror",
        "importerror",
        "timed out",
        "out of memory",
    )
    infrastructure_failure = buggy_status in {
        "ENVIRONMENT_FAILURE", "COLLECTION_ERROR", "TIMEOUT", "SKIPPED", "UNKNOWN"
    } or any(marker in failure_output for marker in infrastructure_markers)
    matches_oracle = (
        buggy_status in behavior_failure_statuses
        and fixed_status == "PASS"
        and not infrastructure_failure
    )
    if matches_oracle:
        reason = "buggy failed while fixed passed"
    elif infrastructure_failure:
        reason = "buggy result indicates an infrastructure, collection, or timeout failure"
    elif buggy_status not in behavior_failure_statuses:
        reason = "buggy result is not a behavioral test failure"
    else:
        reason = "fixed version did not pass"
    return {
        "matches_oracle": matches_oracle,
        "buggy_status": buggy_status,
        "fixed_status": fixed_status,
        "reason": reason,
    }


def _resolve_repo_path(task: dict[str, Any]) -> Path:
    provided_path = Path(task.get("repo_path") or ".")
    if provided_path.exists() and (provided_path / ".git").exists():
        return provided_path

    project_dir = provided_path if provided_path.exists() else provided_path.parent
    project_info = project_dir / "project.info"
    github_url = None
    if project_info.exists():
        for line in project_info.read_text(encoding="utf-8").splitlines():
            if line.startswith("github_url="):
                github_url = line.split("=", 1)[1].strip().strip('"')
                break

    if github_url is None:
        return provided_path

    clone_target = Path(__file__).resolve().parents[2] / ".benchmark_repos" / task.get("project", "unknown")
    if not clone_target.exists():
        clone_target.parent.mkdir(parents=True, exist_ok=True)
        clone_result = run_command(f"git clone --depth 1 {github_url} {clone_target}", cwd=Path(__file__).resolve().parents[2], timeout_seconds=600)
        if clone_result["status"] != "PASS":
            raise RuntimeError(f"Failed to clone benchmark repo for {task.get('project')}: {clone_result['stderr']}")
    return clone_target


def _run_setup_and_test(
    setup_command: str | None,
    test_command: str | None,
    repo_path: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    setup_result = {"status": "SKIPPED", "command": "", "stdout": "", "stderr": "", "returncode": 0, "duration_seconds": 0.0}
    if setup_command:
        setup_result = run_command(setup_command, cwd=repo_path, timeout_seconds=timeout_seconds)

    if not test_command:
        return setup_result, setup_result
    if setup_command and setup_result["status"] != "PASS":
        test_result = {
            "command": test_command,
            "cwd": str(repo_path),
            "status": "ENVIRONMENT_FAILURE",
            "returncode": setup_result["returncode"],
            "stdout": "",
            "stderr": f"Test skipped because setup failed: {setup_result['stderr']}",
            "duration_seconds": 0.0,
        }
        return setup_result, test_result
    return setup_result, run_command(test_command, cwd=repo_path, timeout_seconds=timeout_seconds)


def run_revision(task: dict[str, Any], revision: str, timeout_seconds: int = 300) -> dict[str, Any]:
    repo_path = _resolve_repo_path(task)
    setup_command = task.get("setup_command")
    test_command = task.get("test_command")

    original_head = run_command("git rev-parse --short HEAD", cwd=repo_path, timeout_seconds=timeout_seconds)
    checkout_result = run_command(f"git checkout -q {revision}", cwd=repo_path, timeout_seconds=timeout_seconds)
    if checkout_result["status"] != "PASS":
        return {
            "task_id": task.get("task_id"),
            "project": task.get("project"),
            "commit": revision,
            "checkout": checkout_result,
            "setup": {"status": "SKIPPED", "command": "", "stdout": "", "stderr": "", "returncode": 0, "duration_seconds": 0.0},
            "test": {"status": "SKIPPED", "command": "", "stdout": "", "stderr": "", "returncode": 0, "duration_seconds": 0.0},
            "status": checkout_result.get("status", "UNKNOWN"),
        }

    setup_result, test_result = _run_setup_and_test(
        setup_command,
        test_command,
        repo_path,
        timeout_seconds,
    )

    if original_head.get("status") == "PASS":
        run_command(f"git checkout -q {original_head['stdout'].strip()}", cwd=repo_path, timeout_seconds=timeout_seconds)

    return {
        "task_id": task.get("task_id"),
        "project": task.get("project"),
        "commit": revision,
        "checkout": checkout_result,
        "setup": setup_result,
        "test": test_result,
        "status": test_result.get("status", "UNKNOWN"),
    }


def run_task(task: dict[str, Any], timeout_seconds: int = 300, revision: str | None = None) -> dict[str, Any]:
    if revision is None:
        repo_path = _resolve_repo_path(task)
        setup_command = task.get("setup_command")
        test_command = task.get("test_command")

        setup_result, test_result = _run_setup_and_test(
            setup_command,
            test_command,
            repo_path,
            timeout_seconds,
        )

        return {
            "task_id": task.get("task_id"),
            "project": task.get("project"),
            "setup": setup_result,
            "test": test_result,
            "status": test_result.get("status", "UNKNOWN"),
        }

    return run_revision(task, revision, timeout_seconds=timeout_seconds)


def run_candidate_revision(
    task: dict[str, Any],
    revision: str,
    test_code: str,
    timeout_seconds: int = 120,
    memory_limit_mb: int = 1024,
) -> dict[str, Any]:
    repo_path = _resolve_repo_path(task)
    image = task.get("executor_image")
    if not image:
        test_result = {
            "command": "docker run",
            "cwd": str(repo_path),
            "status": ExecutionStatus.ENVIRONMENT_FAILURE.value,
            "returncode": 2,
            "stdout": "",
            "stderr": "No compatible executor_image is configured for this task.",
            "duration_seconds": 0.0,
        }
        return {
            "task_id": task.get("task_id"),
            "project": task.get("project"),
            "commit": revision,
            "setup": {"status": "SKIPPED", "command": "", "stdout": "", "stderr": "", "returncode": 0, "duration_seconds": 0.0},
            "test": test_result,
            "status": test_result["status"],
        }

    original_head = run_command("git rev-parse --short HEAD", cwd=repo_path, timeout_seconds=timeout_seconds)
    checkout_result = run_command(f"git checkout -q {revision}", cwd=repo_path, timeout_seconds=timeout_seconds)
    setup_result = {
        "status": "SKIPPED",
        "command": f"Dependencies provided by executor image {image}",
        "stdout": "",
        "stderr": "",
        "returncode": 0,
        "duration_seconds": 0.0,
    }
    if checkout_result["status"] != "PASS":
        test_result = {
            "command": "docker run",
            "cwd": str(repo_path),
            "status": ExecutionStatus.ENVIRONMENT_FAILURE.value,
            "returncode": checkout_result["returncode"],
            "stdout": "",
            "stderr": f"Revision checkout failed: {checkout_result['stderr']}",
            "duration_seconds": 0.0,
        }
    else:
        try:
            execution = execute_test_file(
                test_code,
                timeout_seconds=timeout_seconds,
                repo_path=repo_path,
                image=image,
                memory_limit_mb=memory_limit_mb,
            )
            test_result = {
                "command": f"docker run {image} pytest test_generated.py",
                "cwd": str(repo_path),
                "status": execution.status.value,
                "returncode": execution.returncode,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
                "duration_seconds": execution.duration_seconds,
                "coverage": execution.coverage,
            }
        finally:
            if original_head["status"] == "PASS":
                run_command(
                    f"git checkout -q {original_head['stdout'].strip()}",
                    cwd=repo_path,
                    timeout_seconds=timeout_seconds,
                )

    return {
        "task_id": task.get("task_id"),
        "project": task.get("project"),
        "commit": revision,
        "checkout": checkout_result,
        "setup": setup_result,
        "test": test_result,
        "status": test_result["status"],
    }


def run_candidate_task(
    task: dict[str, Any],
    test_code: str,
    timeout_seconds: int = 120,
    memory_limit_mb: int = 1024,
) -> dict[str, Any]:
    buggy = run_candidate_revision(
        task,
        task["buggy_commit"],
        test_code,
        timeout_seconds=timeout_seconds,
        memory_limit_mb=memory_limit_mb,
    )
    fixed = run_candidate_revision(
        task,
        task["fixed_commit"],
        test_code,
        timeout_seconds=timeout_seconds,
        memory_limit_mb=memory_limit_mb,
    )
    return {
        "buggy": buggy,
        "fixed": fixed,
        "oracle": evaluate_oracle(buggy["test"], fixed["test"]),
    }


def load_manifest(path: str | Path) -> list[dict[str, Any]]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Manifest is empty or missing headers: {manifest_path}")

        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing:
            raise ValueError(f"Manifest is missing required columns: {', '.join(missing)}")

        return [dict(row) for row in reader]


def list_pilot_tasks() -> list[dict[str, Any]]:
    manifest_path = Path(__file__).resolve().parents[2] / "benchmarks" / "manifest.csv"
    return load_manifest(manifest_path)
