from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _schemas_registry() -> Registry:
    registry = Registry()
    for name in (
        "experiment_result.schema.json",
        "candidate_test.schema.json",
        "condition_record.schema.json",
        "comparison_summary.schema.json",
    ):
        schema_path = SCHEMA_DIR / name
        resource = Resource.from_contents(
            json.loads(schema_path.read_text(encoding="utf-8")),
            default_specification=DRAFT202012,
        )
        registry = registry.with_resource(schema_path.as_uri(), resource)
    return registry


def render_report(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def write_report(payload: dict[str, Any], output_path: str | Path) -> Path:
    if payload.get("experiment_type") in {
        "benchmark_reproduction",
        "llm_generated_regression_tests",
        "generation_failure",
        "generation_skipped",
    }:
        schema = json.loads((SCHEMA_DIR / "experiment_result.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema, registry=_schemas_registry()).validate(payload)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(render_report(payload))
            handle.write("\n")
        os.replace(temporary_path, destination)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination
