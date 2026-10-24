"""Generate the paper's results figures directly from the frozen analysis artifact.

Usage:
    python scripts/make_paper_figures.py

Reads experiments/results/glm-5.3-flash-free-20261018-v3/analysis.json and writes
docs/paper/figures/fig_results.pdf (vector, for the LaTeX build) and .png (for the
Markdown draft). Number fidelity is guaranteed because every plotted value comes
from the same analysis.json the paper text cites.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "experiments" / "results" / "glm-5.3-flash-free-20261018-v3" / "analysis.json"
OUTDIR = ROOT / "docs" / "paper" / "figures"

CONDITIONS = ("existing_tests", "one_shot", "retrieval", "feedback", "full")
ARM_LABELS = ("A existing", "B one_shot", "C retrieval", "D feedback", "E full")
TASKS = ("bugsinpy-black-021", "bugsinpy-fastapi-012", "bugsinpy-pysnooper-001")
TASK_LABELS = ("Black 021", "FastAPI 012", "PySnooper 001")

DIFFS = (
    ("existing_tests_minus_one_shot", "existing − one_shot"),
    ("retrieval_minus_one_shot", "retrieval − one_shot"),
    ("feedback_minus_one_shot", "feedback − one_shot"),
    ("full_minus_one_shot", "full − one_shot"),
)

COLORS = ("#9CA3AF", "#60A5FA", "#34D399", "#F59E0B", "#111827")


def main() -> None:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    conditions = analysis["conditions"]
    paired = analysis["paired_detection_rate_difference_vs_one_shot_95ci"]

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2), gridspec_kw={"width_ratios": [1.35, 1.0]})
    ax = axes[0]

    x = range(len(CONDITIONS))
    width = 0.28
    for i, (task, label) in enumerate(zip(TASKS, TASK_LABELS)):
        offsets = [xi + (i - 1) * width for xi in x]
        rates = [conditions[c]["per_task"][task]["detection_rate"] for c in CONDITIONS]
        ax.bar(offsets, rates, width=width, label=label, color="#E5E7EB", edgecolor="#9CA3AF",
               linewidth=0.4, hatch="//")
    overall = [conditions[c]["detection_rate"] for c in CONDITIONS]
    ax.bar(
        [xi for xi in x], overall, width=width * 0.9, label="Pooled (3 tasks)",
        color=COLORS, edgecolor="white", linewidth=0.6,
    )
    for xi, rate in zip(x, overall):
        ax.annotate(f"{rate:.2f}", (xi, rate), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(ARM_LABELS, fontsize=9)
    ax.set_ylim(0, 1.08)
    ax.set_yticks([0.0, 0.25, 0.50, 0.75, 1.00])
    ax.set_ylabel("Detection rate", fontsize=10)
    ax.set_title("(a) Detection rate by arm and task", fontsize=10.5)
    ax.legend(fontsize=8, loc="lower right", framealpha=0.9)
    ax.spines[["top", "right"]].set_visible(False)

    ax2 = axes[1]
    labels = [label for _, label in DIFFS]
    means = [paired[key]["mean"] for key, _ in DIFFS]
    err = [[paired[key]["mean"] - paired[key]["lower_95"] for key, _ in DIFFS],
           [paired[key]["upper_95"] - paired[key]["mean"] for key, _ in DIFFS]]
    significance = [paired[key]["lower_95"] > 0 for key, _ in DIFFS]
    bar_colors = ["#111827" if sig else "#9CA3AF" for sig in significance]
    ypos = range(len(DIFFS))
    ax2.barh(list(ypos), means, xerr=err, color=bar_colors,
             height=0.55, error_kw={"capsize": 4, "elinewidth": 1.1})
    for y, key in zip(ypos, [k for k, _ in DIFFS]):
        lo = paired[key]["lower_95"]
        hi = paired[key]["upper_95"]
        ax2.annotate(f"[{lo:+.2f}, {hi:+.2f}]", (hi, y), xytext=(5, -3), textcoords="offset points", fontsize=8)
    ax2.axvline(0.0, color="#111827", linewidth=0.8)
    ax2.set_yticks(list(ypos))
    ax2.set_yticklabels(labels, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlim(-0.45, 0.72)
    ax2.set_xlabel("Δ detection rate vs one_shot", fontsize=10)
    ax2.set_title("(b) Paired lift over one_shot (95% CI)", fontsize=10.5)
    ax2.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTDIR / "fig_results.pdf", bbox_inches="tight")
    fig.savefig(OUTDIR / "fig_results.png", dpi=220, bbox_inches="tight")
    print(f"written: {OUTDIR / 'fig_results.pdf'} and .png")


if __name__ == "__main__":
    main()
