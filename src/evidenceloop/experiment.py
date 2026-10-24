from __future__ import annotations

import platform
import hashlib
import inspect
import ast
import re
from pathlib import Path
import time
from typing import Any

from evidenceloop.benchmark import _resolve_repo_path, run_candidate_task, run_command
from evidenceloop.config import load_config
from evidenceloop.evidence import Evidence, EvidenceStore
from evidenceloop.generator import CandidateGenerator
from evidenceloop.llm import LLMClient
from evidenceloop.prioritizer import (
    CandidateFeature,
    first_fault_detection,
    rank_candidates,
    score_candidate,
)
from evidenceloop.repository import find_test_files, get_changed_files, read_source_file


def _read_context(repo_path: Path, file_names: list[str], max_chars: int) -> str:
    sections = []
    remaining = max_chars
    for file_name in file_names:
        try:
            content = read_source_file(repo_path, file_name)
        except (FileNotFoundError, UnicodeError, ValueError):
            continue
        section = f"### {file_name}\n{content}\n"
        section = section[:remaining]
        if section:
            sections.append(section)
            remaining -= len(section)
        if remaining <= 0:
            break
    return "\n".join(sections)


def _collect_evidence(
    repo_path: Path,
    file_names: list[str],
    evidence_type: str,
    commit: str,
    max_chars: int,
    store: EvidenceStore,
) -> str:
    sections = []
    remaining = max_chars
    for file_name in file_names:
        try:
            raw_content = read_source_file(repo_path, file_name)
        except (FileNotFoundError, UnicodeError, ValueError):
            continue
        content = raw_content[:remaining]
        if not content:
            break
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        evidence_hash = hashlib.sha256(
            f"{commit}\0{evidence_type}\0{file_name}\0{content_hash}".encode("utf-8")
        ).hexdigest()[:16]
        evidence_id = f"ev-{evidence_hash}"
        line_count = len(content.splitlines())
        store.add(
            Evidence(
                evidence_id=evidence_id,
                type=evidence_type,
                path=file_name,
                start_line=1,
                end_line=line_count,
                commit=commit,
                content=content,
                metadata={"sha256": content_hash, "truncated": len(content) < len(raw_content)},
            )
        )
        sections.append(f"### {file_name} [{evidence_id}]\n{content}\n")
        remaining -= len(content)
        if remaining <= 0:
            break
    return "\n".join(sections)


def _normalize_coverage_paths(paths: list[str]) -> list[str]:
    normalized = []
    for path in paths:
        item = path.replace("\\", "/")
        marker = "/workspace/repo/"
        if marker in item:
            item = item.split(marker, 1)[1]
        item = item.removeprefix("./")
        if item not in normalized:
            normalized.append(item)
    return normalized


def _find_direct_callers(repo_path: Path, changed_files: list[str], limit: int = 10) -> list[str]:
    """Find a small, deterministic set of Python files referring to changed symbols."""
    symbols: set[str] = set()
    for name in changed_files:
        if Path(name).suffix != ".py":
            continue
        try:
            tree = ast.parse(read_source_file(repo_path, name))
        except (FileNotFoundError, UnicodeError, ValueError, SyntaxError):
            continue
        symbols.update(
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
    if not symbols:
        return []
    patterns = re.compile(r"\b(?:" + "|".join(re.escape(x) for x in sorted(symbols)) + r")\b")
    changed = {Path(name).as_posix() for name in changed_files}
    results: list[str] = []
    for path in sorted(repo_path.rglob("*.py")):
        relative = path.relative_to(repo_path).as_posix()
        if relative in changed or any(part in {".git", ".venv", "venv", "site-packages", "__pycache__"} for part in path.parts):
            continue
        try:
            text = read_source_file(repo_path, relative)
        except (OSError, UnicodeError, ValueError):
            continue
        if patterns.search(text):
            results.append(relative)
            if len(results) >= limit:
                break
    return results


def run_candidate_experiment(
    task: dict[str, Any],
    bug_summary: str | None = None,
    timeout_seconds: int | None = None,
    llm_client: LLMClient | None = None,
    run_id: str | None = None,
    condition: str = "full",
) -> dict[str, Any]:
    valid_conditions = {"one_shot", "retrieval", "feedback", "full"}
    if condition not in valid_conditions:
        raise ValueError(f"condition must be one of {sorted(valid_conditions)}")
    repo_path = _resolve_repo_path(task)
    buggy_commit = str(task["buggy_commit"])
    fixed_commit = str(task["fixed_commit"])
    original_head = run_command("git rev-parse --short HEAD", cwd=repo_path)
    checkout = run_command(f"git checkout -q {buggy_commit}", cwd=repo_path)
    if checkout["status"] != "PASS":
        raise RuntimeError(f"Unable to checkout the buggy revision: {checkout['stderr']}")

    try:
        changed_files = get_changed_files(repo_path, buggy_commit, fixed_commit)
        changed_python = [name for name in changed_files if Path(name).suffix == ".py"]
        all_tests = find_test_files(repo_path)
        stems = {Path(name).stem.lower() for name in changed_python}
        related_tests = [
            name for name in all_tests if any(stem in Path(name).stem.lower() for stem in stems)
        ][:5]
        direct_callers = _find_direct_callers(repo_path, changed_python)
        if condition == "one_shot":
            related_tests = []

        config_path = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "default.yaml"
        config = load_config(config_path)
        effective_timeout_seconds = timeout_seconds or config.execution.timeout_seconds
        context_limit = min(config.llm.max_input_tokens * 3, 48000)
        evidence_store = EvidenceStore()
        source_context = _collect_evidence(
            repo_path,
            changed_python,
            "changed_source",
            buggy_commit,
            context_limit * 2 // 3,
            evidence_store,
        )
        test_context = _collect_evidence(
            repo_path,
            related_tests,
            "related_test",
            buggy_commit,
            context_limit // 3,
            evidence_store,
        )
        caller_context = _collect_evidence(
            repo_path,
            direct_callers,
            "direct_caller",
            buggy_commit,
            context_limit // 6,
            evidence_store,
        )
        if caller_context:
            source_context = f"{source_context}\n\n## Direct callers\n{caller_context}"
        client = llm_client or LLMClient(
            model=config.llm.model,
            max_output_tokens=config.llm.max_output_tokens,
            max_attempts=config.llm.max_attempts,
        )
        generator = CandidateGenerator(client)
        generation_start = time.monotonic()
        prompt_arguments = {
            "changed_files": changed_files,
            "source_context": source_context,
            "related_tests": test_context,
            "bug_summary": bug_summary,
        }
        if run_id is not None and "run_id" in inspect.signature(generator.generate).parameters:
            prompt_arguments["run_id"] = run_id
        candidates = generator.generate(
            **prompt_arguments,
        )[: config.generation.max_tests_per_task]
        generation_duration = round(time.monotonic() - generation_start, 3)
        model = getattr(client, "model", config.llm.model)
        token_usage = getattr(client, "last_usage", None)
    finally:
        if original_head["status"] == "PASS":
            run_command(
                f"git checkout -q {original_head['stdout'].strip()}",
                cwd=repo_path,
            )

    candidate_results = []
    refinement_stats = {"attempted": False, "repair_attempts": 0, "behavioral_improvements": 0}
    for index, code in enumerate(candidates, start=1):
        execution = run_candidate_task(
            task,
            code,
            timeout_seconds=effective_timeout_seconds,
            memory_limit_mb=config.execution.max_memory_mb,
        )
        candidate_id = f"candidate-{index}"
        coverage = _normalize_coverage_paths(execution["buggy"]["test"].get("coverage", []))
        features = CandidateFeature(
            change_relevance=1.0 if changed_python else 0.0,
            coverage_contribution=float(len(set(changed_python) & set(coverage))),
            execution_cost=float(execution["buggy"]["test"].get("duration_seconds", 0.0)),
            validity=1.0,
            redundancy=0.0,
        )
        candidate_results.append({
            "candidate_id": candidate_id,
            "test_code": code,
            "syntax_valid": True,
            "evidence_ids": evidence_store.evidence_ids(),
            "coverage": coverage,
            "features": features.__dict__,
            "ranking_score": score_candidate(features),
            **execution,
        })

        refinement_enabled = condition in {"feedback", "full"}
        if not refinement_enabled or config.generation.refinement_rounds < 1 or execution["oracle"]["matches_oracle"]:
            continue

        refinement_stats["attempted"] = True
        buggy_test = execution["buggy"]["test"]
        if buggy_test["status"] in {"COLLECTION_ERROR", "EXECUTION_ERROR"}:
            refinement_stats["repair_attempts"] += 1
        buggy_feedback = {
            "status": str(buggy_test.get("status", "UNKNOWN")),
            "stdout": str(buggy_test.get("stdout", ""))[-4000:],
            "stderr": str(buggy_test.get("stderr", ""))[-4000:],
        }
        refined_candidates = generator.refine(
            candidate=code,
            changed_files=changed_files,
            source_context=source_context,
            related_tests=test_context,
            buggy_feedback=buggy_feedback,
            bug_summary=bug_summary,
        )[:1]
        if not refined_candidates:
            continue

        refined_code = refined_candidates[0]
        refined_execution = run_candidate_task(
            task,
            refined_code,
            timeout_seconds=effective_timeout_seconds,
            memory_limit_mb=config.execution.max_memory_mb,
        )
        if refined_execution["oracle"]["matches_oracle"]:
            refinement_stats["behavioral_improvements"] += 1
        refined_features = CandidateFeature(
            change_relevance=features.change_relevance,
            coverage_contribution=features.coverage_contribution,
            execution_cost=float(refined_execution["buggy"]["test"].get("duration_seconds", 0.0)),
            validity=1.0,
            redundancy=0.0,
        )
        candidate_results.append({
            "candidate_id": f"{candidate_id}-refined-1",
            "parent_candidate_id": candidate_id,
            "test_code": refined_code,
            "syntax_valid": True,
            "evidence_ids": evidence_store.evidence_ids(),
            "coverage": _normalize_coverage_paths(refined_execution["buggy"]["test"].get("coverage", [])),
            "features": refined_features.__dict__,
            "ranking_score": score_candidate(refined_features),
            "refinement_round": 1,
            **refined_execution,
        })

    ranking_candidates = [
        {
            "candidate_id": item["candidate_id"],
            "features": item["features"],
            "coverage": item.get("coverage", []),
        }
        for item in candidate_results
    ]
    rankings = rank_candidates(ranking_candidates, random_seed=42)
    for ranking_name, order in rankings.items():
        for rank, candidate_id in enumerate(order, start=1):
            for item in candidate_results:
                if item["candidate_id"] == candidate_id:
                    item.setdefault("ranking_positions", {})[ranking_name] = rank
    fault_detecting = {
        item["candidate_id"]
        for item in candidate_results
        if item.get("oracle", {}).get("matches_oracle") is True
    }
    early_detection = {
        name: first_fault_detection(order, fault_detecting)
        for name, order in rankings.items()
    }

    return {
        "schema_version": "1.0",
        "experiment_type": "llm_generated_regression_tests",
        "condition": condition,
        "task_id": task.get("task_id"),
        "project": task.get("project"),
        "run_id": run_id,
        "model": model,
        "provider": getattr(client, "provider", None),
        "provider_attempts": getattr(client, "attempt_diagnostics", []),
        "response_diagnostics": getattr(client, "response_diagnostics", []),
        "prompt_version": "v2",
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "experiment_config": {
            "max_input_tokens": config.llm.max_input_tokens,
            "max_output_tokens": config.llm.max_output_tokens,
            "max_attempts": config.llm.max_attempts,
            "max_tests_per_task": config.generation.max_tests_per_task,
            "refinement_rounds": config.generation.refinement_rounds,
            "timeout_seconds": effective_timeout_seconds,
            "max_memory_mb": config.execution.max_memory_mb,
            "temperature": 0.2,
            "thinking_level": "low",
        },
        "generation_duration_seconds": generation_duration,
        "token_usage": getattr(client, "total_usage", None) or token_usage,
        "api_cost_usd": None,
        "generation_revision": buggy_commit,
        "scoring_revision": fixed_commit,
        "evidence": {
            "changed_files": changed_files,
            "related_tests": related_tests,
            "direct_callers": direct_callers,
            "items": evidence_store.as_dicts(),
        },
        "refinement": refinement_stats,
        "ranking": {
            "enabled": condition == "full",
            "random_seed": 42,
            "orders": rankings if condition == "full" else {},
            "early_detection": early_detection if condition == "full" else {},
        },
        "candidate_tests": candidate_results,
    }
