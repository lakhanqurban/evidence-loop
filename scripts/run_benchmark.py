from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evidenceloop.benchmark import list_pilot_tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="List pilot BugsInPy benchmark tasks.")
    parser.add_argument("--manifest", type=str, default=str(Path(__file__).resolve().parents[1] / "benchmarks" / "manifest.csv"), help="Path to the benchmark manifest")
    args = parser.parse_args()

    tasks = list_pilot_tasks() if Path(args.manifest).name == "manifest.csv" else []
    for task in tasks:
        print(task["task_id"], "->", task["project"])


if __name__ == "__main__":
    main()
