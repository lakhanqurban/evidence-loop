from evidenceloop.analyzer import summarize_changed_file


def test_summarize_changed_file(tmp_path):
    file_path = tmp_path / "sample.py"
    file_path.write_text("def demo():\n    return 1\n\nclass A:\n    pass\n", encoding="utf-8")

    summary = summarize_changed_file(file_path)
    assert summary["symbol_count"] == 2
    assert summary["symbols"][0]["name"] == "demo"
