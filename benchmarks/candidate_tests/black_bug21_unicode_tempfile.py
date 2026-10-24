from pathlib import Path

import black


def test_dump_to_file_accepts_unicode_text():
    temporary_path = Path(black.dump_to_file("value = 'ł'\n"))

    try:
        assert temporary_path.is_file()
    finally:
        temporary_path.unlink(missing_ok=True)