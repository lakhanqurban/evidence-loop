from pathlib import Path

from evidenceloop.repository import _repo_root, find_test_files, read_source_file


def test_repo_root_validation(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    assert _repo_root(repo_dir) == repo_dir.resolve()


def test_read_source_file(tmp_path):
    repo_dir = tmp_path / "repo"
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True)
    file_path = src_dir / "demo.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    content = read_source_file(repo_dir, "src/demo.py")
    assert "def add" in content


def test_find_test_files(tmp_path):
    repo_dir = tmp_path / "repo"
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_example.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    assert "tests/test_example.py" in find_test_files(repo_dir)
