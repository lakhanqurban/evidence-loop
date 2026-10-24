from __future__ import annotations

import json
from pathlib import Path

import typer

from evidenceloop.analyzer import summarize_changed_file
from evidenceloop.benchmark import evaluate_oracle, list_pilot_tasks, load_manifest, run_task
from evidenceloop.config import load_config
from evidenceloop.experiment import run_candidate_experiment
from evidenceloop.generator import CandidateGenerator
from evidenceloop.llm import LLMClient
from evidenceloop.repository import find_test_files, get_changed_files, read_source_file
from evidenceloop.reporter import write_report

app = typer.Typer(help="EvidenceLoop CLI")


@app.command()
def analyze(repo: str, base: str, target: str) -> None:
    changed = get_changed_files(repo, base, target)
    payload = {"repo": repo, "base": base, "target": target, "changed_files": changed}
    for file_name in changed:
        path = Path(repo) / file_name
        if path.exists():
            payload.setdefault("details", {})[file_name] = summarize_changed_file(path)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _read_context(repo: str, file_names: list[str], max_chars: int) -> str:
    parts = []
    remaining = max_chars
    for file_name in file_names:
        try:
            content = read_source_file(repo, file_name)
        except (FileNotFoundError, UnicodeError, ValueError):
            continue
        section = f"### {file_name}\n{content}\n"
        if len(section) > remaining:
            section = section[:remaining]
        if section:
            parts.append(section)
            remaining -= len(section)
        if remaining <= 0:
            break
    return "\n".join(parts)


@app.command()
def generate(
    repo: str,
    base: str,
    target: str,
    bug_summary: str | None = None,
    output: str | None = None,
) -> None:
    config_path = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "default.yaml"
    config = load_config(config_path)
    changed = get_changed_files(repo, base, target)
    changed_python = [file_name for file_name in changed if Path(file_name).suffix == ".py"]
    test_files = find_test_files(repo)
    changed_stems = {Path(file_name).stem.lower() for file_name in changed_python}
    related_tests = [
        file_name
        for file_name in test_files
        if any(stem in Path(file_name).stem.lower() for stem in changed_stems)
    ][:5]
    context_budget = min(config.llm.max_input_tokens * 3, 48000)
    source_context = _read_context(repo, changed_python, context_budget * 2 // 3)
    test_context = _read_context(repo, related_tests, context_budget // 3)
    candidates = CandidateGenerator(
        LLMClient(
            model=config.llm.model,
            max_output_tokens=config.llm.max_output_tokens,
            max_attempts=config.llm.max_attempts,
        )
    ).generate(
        changed_files=changed,
        source_context=source_context,
        related_tests=test_context,
        bug_summary=bug_summary,
    )[: config.generation.max_tests_per_task]
    payload = {
        "repo": repo,
        "base": base,
        "target": target,
        "model": config.llm.model,
        "changed_files": changed,
        "related_tests": related_tests,
        "prompt_version": "v2",
        "candidate_tests": [
            {"candidate_id": f"candidate-{index}", "test_code": code, "syntax_valid": True}
            for index, code in enumerate(candidates, start=1)
        ],
    }
    if output:
        write_report(payload, output)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def benchmark(
    manifest: str = "benchmarks/manifest.csv",
    task_id: str | None = None,
    reproduce: bool = False,
    output: str | None = None,
) -> None:
    manifest_path = Path(manifest)
    if not manifest_path.exists():
        raise typer.BadParameter(f"Manifest file not found: {manifest}")

    tasks = load_manifest(manifest_path)
    if task_id is not None:
        tasks = [task for task in tasks if task.get("task_id") == task_id]

    if reproduce:
        executed = []
        for task in tasks:
            buggy_result = run_task(task, timeout_seconds=600, revision=task.get("buggy_commit"))
            fixed_result = run_task(task, timeout_seconds=600, revision=task.get("fixed_commit"))
            executed.append(
                {
                    "task_id": task.get("task_id"),
                    "project": task.get("project"),
                    "buggy": buggy_result,
                    "fixed": fixed_result,
                    "oracle": evaluate_oracle(buggy_result["test"], fixed_result["test"]),
                }
            )
        payload = {"manifest": str(manifest_path), "tasks": executed}
    else:
        payload = {"manifest": str(manifest_path), "tasks": tasks}
    if output:
        write_report(payload, output)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def evaluate(manifest: str, output: str | None = None) -> None:
    manifest_path = Path(manifest)
    if not manifest_path.exists():
        raise typer.BadParameter(f"Manifest file not found: {manifest}")
    payload = {"manifest": str(manifest_path), "tasks": load_manifest(manifest_path)}
    if output:
        write_report(payload, output)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def experiment(
    task_id: str,
    output: str = typer.Option(..., "--output"),
    manifest: str = "benchmarks/manifest.csv",
    bug_summary: str | None = None,
) -> None:
    manifest_path = Path(manifest)
    if not manifest_path.exists():
        raise typer.BadParameter(f"Manifest file not found: {manifest}")
    matches = [task for task in load_manifest(manifest_path) if task.get("task_id") == task_id]
    if len(matches) != 1:
        raise typer.BadParameter(f"Expected one manifest task with id {task_id!r}; found {len(matches)}")

    payload = run_candidate_experiment(matches[0], bug_summary=bug_summary)
    write_report(payload, output)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
