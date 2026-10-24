from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable


ALLOWED_SOURCE_EXTENSIONS = {".py"}
BLOCKED_FILE_NAMES = {".env", ".env.local", ".secrets", "secrets.env"}


def _repo_root(repo_path: str | os.PathLike[str]) -> Path:
    root = Path(repo_path).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {root}")
    return root


def _safe_join(repo_root: Path, file_path: str) -> Path:
    candidate = (repo_root / file_path).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:  # pragma: no cover
        raise ValueError(f"Path escapes repository root: {file_path}") from exc
    return candidate


def get_changed_files(repo_path: str | os.PathLike[str], base_commit: str, target_commit: str) -> list[str]:
    """Return files changed between two commits in a Git repository."""
    root = _repo_root(repo_path)
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", base_commit, target_commit],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unable to determine changed files.")
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [item for item in files if item and not item.startswith("\n")]


def read_source_file(repo_path: str | os.PathLike[str], file_path: str) -> str:
    root = _repo_root(repo_path)
    safe_path = _safe_join(root, file_path)

    if safe_path.name in BLOCKED_FILE_NAMES:
        raise ValueError(f"Blocked file: {file_path}")
    if safe_path.suffix.lower() not in ALLOWED_SOURCE_EXTENSIONS:
        raise ValueError(f"Unsupported source file type: {file_path}")
    if not safe_path.exists() or not safe_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    return safe_path.read_text(encoding="utf-8")


def find_test_files(repo_path: str | os.PathLike[str]) -> list[str]:
    """Discover test files using common repository conventions."""
    root = _repo_root(repo_path)
    matches: list[str] = []
    for current_root, _, files in os.walk(root):
        if ".git" in current_root.split(os.sep):
            continue
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            lower = file_name.lower()
            if lower.startswith("test_") or lower.endswith("_test.py") or "test" in lower:
                rel_path = Path(current_root, file_name).relative_to(root).as_posix()
                matches.append(rel_path)
    return sorted(matches)


def find_changed_functions(repo_path: str | os.PathLike[str], base_commit: str, target_commit: str) -> list[str]:
    """A small helper to root the analysis around changed files and function names."""
    changed = get_changed_files(repo_path, base_commit, target_commit)
    candidates: list[str] = []
    for file_name in changed:
        if file_name.endswith(".py"):
            candidates.append(file_name)
    return candidates
