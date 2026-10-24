"""Schema validation quality gate over emitted experiment reports.

Usage:
    python scripts/validate_artifacts.py [PATHS...]          # default: experiments/results
    python scripts/validate_artifacts.py --fail-fast PATHS...

Classifies every JSON report by `experiment_type` (or the compact condition
record shape used inside summary files) and validates it against the JSON
schemas in schemas/. Exits 1 if any report fails validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"

SCHEMA_FILES = (
    "experiment_result.schema.json",
    "candidate_test.schema.json",
    "condition_record.schema.json",
    "comparison_summary.schema.json",
)
TYPE_SELECTOR = {
    "benchmark_reproduction": "BenchmarkReproduction",
    "llm_generated_regression_tests": "GeneratedCandidateExperiment",
    "generation_failure": "GeneratedFailureReport",
    "generation_skipped": "SkippedGenerationReport",
}


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _registry():
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for name in SCHEMA_FILES:
        resource = Resource.from_contents(_load_schema(name), default_specification=DRAFT202012)
        registry = registry.with_resource((SCHEMA_DIR / name).as_uri(), resource)
    return registry


def _def_schema(definition: str) -> dict[str, Any]:
    """Build a schema validating exactly one definition of experiment_result.schema.json."""
    full = _load_schema("experiment_result.schema.json")
    return {
        "$schema": full["$schema"],
        "$id": (SCHEMA_DIR / "experiment_result.schema.json").as_uri(),
        "$defs": full["$defs"],
        "$ref": f"#/$defs/{definition}",
    }


def _classify(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    experiment_type = payload.get("experiment_type")
    if experiment_type in TYPE_SELECTOR:
        return TYPE_SELECTOR[experiment_type]
    if "condition" in payload and "run_id" in payload:
        return "condition_record"
    if "records" in payload and "conditions" in payload:
        return "summary_container"
    return "unknown"


def _validate_with(schema: dict[str, Any], payload: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema, registry=_registry())
    return [error.message for error in validator.iter_errors(payload)]


def validate_file(path: Path) -> tuple[str, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "unreadable", [str(exc)]

    definition = _classify(payload)
    if definition == "condition_record":
        errors = _validate_with(_load_schema("condition_record.schema.json"), payload)
    elif definition == "summary_container":
        errors = _validate_with(_load_schema("comparison_summary.schema.json"), payload)
    elif definition == "unknown":
        return "unknown-shape", ["could not classify report by experiment_type or condition shape"]
    else:
        errors = _validate_with(_def_schema(definition), payload)

    status = "valid" if not errors else "invalid"
    return status, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate emitted experiment reports against the JSON schemas.")
    parser.add_argument("paths", nargs="*", type=Path, help="Files or directories to validate (default: experiments/results).")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="DIRNAME",
        help="Skip artifacts under a directory matching this name (repeatable; e.g. pre-freeze legacy runs).",
    )
    args = parser.parse_args(argv)
    excluded = tuple(args.exclude)

    targets: list[Path] = []
    for raw in args.paths or [ROOT / "experiments" / "results"]:
        path = Path(raw)
        if path.is_file():
            targets.append(path)
        else:
            targets.extend(sorted(path.rglob("*.json")))
    json_targets = [path for path in targets if path.suffix == ".json" and path.name != "analysis.json"]

    checked = 0
    failures = 0
    unknown = 0
    excluded_count = 0
    for path in json_targets:
        if excluded and any(part in excluded for part in path.parts):
            excluded_count += 1
            continue
        status, errors = validate_file(path)
        checked += 1
        if status == "valid":
            continue
        if status in {"invalid", "unreadable"}:
            failures += 1
            print(f"FAIL {path}")
            for error in errors[:5]:
                print(f"     {error}")
            if args.fail_fast:
                break
        else:
            unknown += 1
            print(f"SKIP {path} ({errors[0] if errors else status})")

    print(f"checked={checked} valid={checked - failures - unknown} invalid={failures} unclassified={unknown} excluded={excluded_count}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
