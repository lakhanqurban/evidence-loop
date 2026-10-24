from pathlib import Path

import yaml


def test_frozen_protocol_covers_manifest_tasks_controls_and_repetitions():
    protocol_path = Path(__file__).resolve().parents[1] / "experiments" / "configs" / "protocol-v1.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))

    assert protocol["status"] == "frozen-for-pilot"
    assert set(protocol["task_ids"]) == {"bugsinpy-black-021", "bugsinpy-fastapi-012"}
    assert protocol["generation"]["refinement_rounds"] == 1
    assert protocol["isolation"]["network"] == "disabled"
    assert protocol["repetitions"]["live_model_runs_per_task"] >= 2
    assert protocol["analysis"]["confidence_level"] == 0.95