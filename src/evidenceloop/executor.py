from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


class ExecutionStatus(str, enum.Enum):
    PASS = "PASS"
    ASSERTION_FAILURE = "ASSERTION_FAILURE"
    COLLECTION_ERROR = "COLLECTION_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"


class ExecutionResult:
    def __init__(self, status: ExecutionStatus, stdout: str = "", stderr: str = "", returncode: int = 0, duration_seconds: float = 0.0, coverage: list[str] | None = None) -> None:
        self.status = status
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.duration_seconds = duration_seconds
        self.coverage = coverage or []


def _ignore_sandbox_files(directory: str, names: list[str]) -> set[str]:
    excluded = {
        ".aws",
        ".azure",
        ".git",
        ".netrc",
        ".pytest_cache",
        ".secrets",
        ".ssh",
        ".venv",
        "__pycache__",
        "credentials",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "node_modules",
        "secrets",
        "secrets.env",
        "service-account.json",
        "venv",
    }
    return {
        name
        for name in names
        if name.lower() in excluded
        or name.lower().startswith(".env")
        or name.lower().endswith((".key", ".pem", ".p12", ".pfx"))
    }


def _classify_test_result(returncode: int, stdout: str, stderr: str) -> ExecutionStatus:
    output = f"{stdout}\n{stderr}"
    if returncode == 0:
        return ExecutionStatus.PASS
    if returncode in {125, 126, 127} or "Cannot connect to the Docker daemon" in output:
        return ExecutionStatus.ENVIRONMENT_FAILURE
    if "ImportError" in output or "ModuleNotFoundError" in output or "ERROR collecting" in output:
        return ExecutionStatus.COLLECTION_ERROR
    if "no tests ran" in output.lower():
        return ExecutionStatus.COLLECTION_ERROR
    if "AssertionError" in output or re.search(r"\bassert\s+.*\bfailed\b", output.lower()):
        return ExecutionStatus.ASSERTION_FAILURE
    return ExecutionStatus.EXECUTION_ERROR


def _extract_coverage_files(output: str) -> list[str]:
    coverage_files = []
    for line in output.splitlines():
        match = re.match(r"\s*(.+?\.py)\s+\d+\s+\d+\s+\d+%", line)
        if match:
            path = match.group(1).strip().replace("\\", "/")
            if path not in coverage_files:
                coverage_files.append(path)
    return coverage_files


def execute_test_file(
    test_code: str,
    timeout_seconds: int = 60,
    repo_path: str | Path | None = None,
    image: str | None = None,
    memory_limit_mb: int = 1024,
) -> ExecutionResult:
    """Run generated tests in a disposable, network-isolated Docker container."""
    docker = shutil.which("docker")
    if docker is None:
        return ExecutionResult(
            status=ExecutionStatus.ENVIRONMENT_FAILURE,
            stderr="Docker is required; generated tests are never run on the host.",
            returncode=127,
        )

    source_root = Path(repo_path or Path.cwd()).resolve()
    if not source_root.is_dir():
        return ExecutionResult(
            status=ExecutionStatus.ENVIRONMENT_FAILURE,
            stderr=f"Repository path is not a directory: {source_root}",
            returncode=2,
        )

    selected_image = image or os.getenv("EVIDENCELOOP_EXECUTOR_IMAGE", "evidenceloop-runner:local")
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="evidenceloop-sandbox-") as temp_dir:
        temp_root = Path(temp_dir)
        staged_repo = temp_root / "repo"
        candidate_dir = temp_root / "candidate"
        candidate_dir.mkdir()
        (candidate_dir / "test_generated.py").write_text(test_code, encoding="utf-8")

        try:
            shutil.copytree(
                source_root,
                staged_repo,
                symlinks=True,
                ignore=_ignore_sandbox_files,
            )
        except OSError as exc:
            return ExecutionResult(
                status=ExecutionStatus.ENVIRONMENT_FAILURE,
                stderr=f"Unable to stage a sanitized repository copy: {exc}",
                returncode=2,
                duration_seconds=round(time.monotonic() - start, 3),
            )

        command = [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cpus",
            "1",
            "--memory",
            f"{memory_limit_mb}m",
            "--pids-limit",
            "64",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m,mode=1777,uid=65534,gid=65534",
            "--mount",
            f"type=bind,source={staged_repo.as_posix()},target=/workspace/repo,readonly",
            "--mount",
            f"type=bind,source={candidate_dir.as_posix()},target=/workspace/candidate,readonly",
            "--workdir",
            "/workspace/repo",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONPATH=/workspace/repo:/workspace/repo/src",
            "--env",
            "COVERAGE_FILE=/tmp/.coverage",
            selected_image,
            "python",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--cov=/workspace/repo",
            "--cov-report=term:skip-covered",
            "/workspace/candidate/test_generated.py",
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                returncode=124,
                duration_seconds=round(time.monotonic() - start, 3),
            )
        except OSError as exc:
            return ExecutionResult(
                status=ExecutionStatus.ENVIRONMENT_FAILURE,
                stderr=f"Unable to start Docker: {exc}",
                returncode=127,
                duration_seconds=round(time.monotonic() - start, 3),
            )

    duration = round(time.monotonic() - start, 3)
    status = _classify_test_result(completed.returncode, completed.stdout, completed.stderr)
    return ExecutionResult(
        status=status,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        duration_seconds=duration,
        coverage=_extract_coverage_files(f"{completed.stdout}\n{completed.stderr}"),
    )
