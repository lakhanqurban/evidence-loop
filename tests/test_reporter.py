import json

from evidenceloop.reporter import write_report


def test_write_report_creates_parent_and_persists_json(tmp_path):
    destination = tmp_path / "runs" / "result.json"
    payload = {"task_id": "task-1", "oracle": {"matches_oracle": True}}

    written_path = write_report(payload, destination)

    assert written_path == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == payload